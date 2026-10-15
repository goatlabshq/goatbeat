from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection

from goatbeat.core.misfire import MisfirePolicy
from goatbeat.core.registry import DEFAULT_INTERVAL_ANCHOR
from goatbeat.core.schedule import Routing, ScheduleSource
from goatbeat.core.tasks import TaskCall
from goatbeat.core.time import Instant
from goatbeat.core.triggers import CronTrigger, IntervalTrigger
from goatbeat.django.celery_beat import Crontab, Interval, LegacyTask, convert
from goatbeat.django.runtime import store
from goatbeat.django.submitter import routing_problem

TASK = LegacyTask(
    name="nightly",
    task="sampleapp.tasks.send_report",
    args="[]",
    kwargs="{}",
    queue=None,
    priority=None,
    enabled=True,
    one_off=False,
    start_time=None,
    expires=None,
    expire_seconds=None,
    exchange=None,
    routing_key=None,
    headers="{}",
    interval=None,
    crontab=Crontab("0", "3", "*", "*", "mon-fri", "Europe/Paris"),
    solar=False,
    clocked=False,
)


def always(path: str) -> bool:
    del path
    return True


def refuse_routing(path: str, routing: Routing) -> str:
    del path, routing
    return "bad queue"


def never(path: str) -> bool:
    del path
    return False


def test_a_crontab_becomes_a_cron_trigger_in_its_timezone() -> None:
    result = convert(TASK, task_exists=always)
    assert result.definition is not None
    trigger = result.definition.trigger
    assert isinstance(trigger, CronTrigger)
    assert trigger.expression.text == "0 3 * * mon-fri"
    assert trigger.timezone.key == "Europe/Paris"
    assert result.definition.misfire.policy is MisfirePolicy.RUN_ONCE
    assert result.notes == ()


@pytest.mark.parametrize(
    ("period", "every", "expected"),
    [
        ("days", 2, timedelta(days=2)),
        ("hours", 1, timedelta(hours=1)),
        ("minutes", 15, timedelta(minutes=15)),
        ("seconds", 30, timedelta(seconds=30)),
        ("microseconds", 500_000, timedelta(milliseconds=500)),
    ],
)
def test_an_interval_becomes_an_interval_trigger(
    period: str, every: int, expected: timedelta
) -> None:
    legacy = replace(TASK, crontab=None, interval=Interval(every, period))
    result = convert(legacy, task_exists=always)
    assert result.definition is not None
    assert result.definition.trigger == IntervalTrigger(expected, DEFAULT_INTERVAL_ANCHOR)


def test_the_start_time_anchors_an_interval() -> None:
    start = datetime(2026, 1, 1, 8, 30, tzinfo=UTC)
    legacy = replace(TASK, crontab=None, interval=Interval(1, "hours"), start_time=start)
    result = convert(legacy, task_exists=always)
    assert result.definition is not None
    assert result.definition.trigger == IntervalTrigger(timedelta(hours=1), Instant.of(start))


def test_arguments_queue_priority_and_enabled_are_kept() -> None:
    legacy = replace(
        TASK,
        task="sampleapp.tasks.send_email",
        args="[7]",
        kwargs='{"subject": "hi"}',
        queue="emails",
        priority=4,
        enabled=False,
    )
    result = convert(legacy, task_exists=always)
    assert result.definition is not None
    assert result.definition.task == TaskCall("sampleapp.tasks.send_email", (7,), {"subject": "hi"})
    assert (result.definition.routing.queue, result.definition.routing.priority) == ("emails", 4)
    assert not result.definition.enabled


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"crontab": None, "solar": True}, "solar"),
        ({"crontab": None, "clocked": True}, "clocked"),
        ({"crontab": None}, "no schedule"),
        ({"args": "not json"}, "arguments"),
        ({"crontab": Crontab("61", "*", "*", "*", "*", "UTC")}, "cron"),
        ({"crontab": Crontab("0", "3", "*", "*", "*", "Mars/Base")}, "timezone"),
    ],
)
def test_schedules_goatbeat_cannot_express_are_skipped(
    change: dict[str, object], reason: str
) -> None:
    result = convert(replace(TASK, **change), task_exists=always)
    assert result.definition is None
    assert reason in " ".join(result.notes)


def test_options_goatbeat_does_not_support_are_reported() -> None:
    legacy = replace(
        TASK,
        one_off=True,
        expires=datetime(2027, 1, 1, tzinfo=UTC),
        exchange="ex",
        routing_key="rk",
        headers='{"h": 1}',
    )
    result = convert(legacy, task_exists=always)
    assert result.definition is not None
    notes = " ".join(result.notes)
    for option in ("one_off", "expires", "exchange", "routing_key", "headers"):
        assert option in notes


def test_both_day_fields_restricted_is_skipped_because_matching_differs() -> None:
    legacy = replace(TASK, crontab=Crontab("0", "9", "1", "*", "mon", "UTC"))
    result = convert(legacy, task_exists=always)
    assert result.definition is None
    assert "day of month and day of week" in " ".join(result.notes)


@pytest.mark.parametrize(
    "change",
    [{"crontab": None, "interval": Interval(2**31 - 1, "days")}, {"name": "   "}],
)
def test_rows_goatbeat_rejects_are_skipped_not_raised(change: dict[str, object]) -> None:
    result = convert(replace(TASK, **change), task_exists=always)
    assert result.definition is None
    assert result.notes


def test_routing_the_backend_refuses_is_imported_disabled() -> None:
    legacy = replace(TASK, queue="celery", priority=200)
    result = convert(legacy, task_exists=always, routing_problem=refuse_routing)
    assert result.definition is not None
    assert not result.definition.enabled
    assert "bad queue" in " ".join(result.notes)


def test_start_time_and_expire_seconds_on_crontabs_are_reported() -> None:
    start = datetime(2027, 1, 1, tzinfo=UTC)
    result = convert(replace(TASK, start_time=start, expire_seconds=60), task_exists=always)
    notes = " ".join(result.notes)
    assert "start_time" in notes
    assert "expire_seconds" in notes


def test_a_task_that_is_not_a_django_task_is_imported_disabled() -> None:
    result = convert(TASK, task_exists=never)
    assert result.definition is not None
    assert not result.definition.enabled
    assert "not a Django task" in " ".join(result.notes)


LEGACY_DDL = (
    (
        "CREATE TABLE django_celery_beat_intervalschedule "
        "(id serial PRIMARY KEY, every integer NOT NULL, period varchar(24) NOT NULL)"
    ),
    (
        "CREATE TABLE django_celery_beat_crontabschedule (id serial PRIMARY KEY, "
        "minute varchar(240), hour varchar(96), day_of_week varchar(64), "
        "day_of_month varchar(124), month_of_year varchar(64), timezone varchar(63))"
    ),
    (
        "CREATE TABLE django_celery_beat_periodictask (id serial PRIMARY KEY, "
        "name varchar(200) UNIQUE, task varchar(200), interval_id integer, crontab_id integer, "
        "solar_id integer, clocked_id integer, args text, kwargs text, queue varchar(200), "
        "exchange varchar(200), routing_key varchar(200), headers text, priority integer, "
        "expires timestamptz, expire_seconds integer, one_off boolean, start_time timestamptz, "
        "enabled boolean)"
    ),
    "INSERT INTO django_celery_beat_intervalschedule VALUES (1, 5, 'minutes')",
    "INSERT INTO django_celery_beat_crontabschedule VALUES (1, '0', '9', '1', '*', '*', 'UTC')",
    (
        "INSERT INTO django_celery_beat_periodictask (name, task, interval_id, crontab_id, "
        "solar_id, clocked_id, args, kwargs, queue, exchange, routing_key, headers, priority, "
        "expires, "
        "one_off, start_time, enabled) VALUES "
        "('legacy-ping', 'sampleapp.tasks.send_email', 1, NULL, NULL, NULL, '[3]', '{}', NULL, "
        "NULL, NULL, '{}', NULL, NULL, false, NULL, true), "
        "('legacy-weekly', 'sampleapp.tasks.send_report', NULL, 1, NULL, NULL, '[]', '{}', NULL, "
        "NULL, NULL, '{}', NULL, NULL, false, NULL, true), "
        "('legacy-solar', 'sampleapp.tasks.send_report', NULL, NULL, 1, NULL, '[]', '{}', NULL, "
        "NULL, NULL, '{}', NULL, NULL, false, NULL, true), "
        "('ping', 'sampleapp.tasks.send_report', 1, NULL, NULL, NULL, '[]', '{}', NULL, "
        "NULL, NULL, '{}', NULL, NULL, false, NULL, true)"
    ),
)


@pytest.fixture
def legacy_tables() -> Iterator[None]:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO goatbeat_lease VALUES (0, NULL, 0, '-infinity') ON CONFLICT DO NOTHING"
        )
        for statement in LEGACY_DDL:
            cursor.execute(statement)
    yield
    with connection.cursor() as cursor:
        cursor.execute(
            "DROP TABLE django_celery_beat_periodictask, django_celery_beat_crontabschedule, "
            "django_celery_beat_intervalschedule"
        )


def import_beat(*arguments: str) -> str:
    output = StringIO()
    call_command("goatbeat", "import_celery_beat", *arguments, stdout=output)
    return output.getvalue()


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("legacy_tables")
def test_the_command_imports_and_reports_every_periodic_task() -> None:
    import_beat("--dry-run")
    assert store().get_schedule("legacy-ping") is None
    store().sync_code_schedules([], Instant.of(datetime.now(UTC)))
    call_command("goatbeat", "schedule", "list", stdout=StringIO())
    report = import_beat()
    assert "imported legacy-ping" in report
    assert "imported legacy-weekly" in report
    assert "skipped legacy-solar" in report
    assert "skipped ping" in report
    weekly = store().get_schedule("legacy-weekly")
    assert weekly is not None
    assert weekly.source is ScheduleSource.STORE
    assert isinstance(weekly.definition.trigger, CronTrigger)
    assert weekly.definition.trigger.expression.text == "0 9 * * 1"
    assert "skipped legacy-ping" in import_beat()


@pytest.mark.django_db(transaction=True)
def test_the_command_explains_a_missing_celery_beat_table() -> None:
    from django.core.management import CommandError

    with pytest.raises(CommandError, match="django_celery_beat"):
        import_beat()


def test_valid_django_routing_is_accepted() -> None:
    assert (
        routing_problem("sampleapp.tasks.send_report", Routing(queue="emails", priority=10)) is None
    )


@pytest.mark.parametrize("routing", [Routing(priority=200), Routing(queue="celery")])
def test_django_routing_the_backend_refuses_is_reported(routing: Routing) -> None:
    assert routing_problem("sampleapp.tasks.send_report", routing) is not None
