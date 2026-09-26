import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.test import Client

from goatbeat.core.execution import ExecutionStatus
from goatbeat.core.ids import IdempotencyKey, SchedulerId
from goatbeat.core.schedule import ScheduleSource
from goatbeat.core.tasks import TaskCall
from goatbeat.core.time import SystemClock
from goatbeat.core.triggers import CronTrigger, IntervalTrigger
from goatbeat.django import registry
from goatbeat.django.runtime import store

pytestmark = pytest.mark.django_db(transaction=True)

CHANGELIST = "/admin/goatbeat/schedule/"
ADD = "/admin/goatbeat/schedule/add/"

VALID_CRON = {
    "name": "nightly",
    "task_path": "sampleapp.tasks.send_report",
    "task_args": "[]",
    "task_kwargs": "{}",
    "trigger_kind": "cron",
    "cron": "0 3 * * *",
    "timezone": "Europe/Paris",
    "every": "",
    "misfire_policy": "run_once",
    "misfire_grace_seconds": "60",
    "max_catch_up": "100",
    "queue": "",
    "priority": "",
    "backend": "",
    "enabled": "on",
}


@pytest.fixture
def admin_client() -> Client:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO goatbeat_lease VALUES (0, NULL, 0, '-infinity') ON CONFLICT DO NOTHING"
        )
    store().sync_code_schedules(registry().definitions(), SystemClock().now())
    client = Client()
    client.force_login(User.objects.create_superuser("admin", "admin@example.com", "pw"))
    return client


def schedule_id(name: str) -> str:
    schedule = store().get_schedule(name)
    assert schedule is not None
    return schedule.id.value


def test_the_changelist_shows_schedules(admin_client: Client) -> None:
    page = admin_client.get(CHANGELIST)
    assert page.status_code == 200
    assert b"daily-report" in page.content
    assert b"every 0:05:00" in page.content


def test_a_cron_schedule_is_created_through_the_store(admin_client: Client) -> None:
    response = admin_client.post(ADD, VALID_CRON)
    assert response.status_code == 302, response.content
    created = store().get_schedule("nightly")
    assert created is not None
    assert created.source is ScheduleSource.STORE
    assert isinstance(created.definition.trigger, CronTrigger)
    assert created.definition.trigger.timezone.key == "Europe/Paris"
    assert created.next_run_at == created.definition.trigger.next_after(SystemClock().now())


def test_an_interval_schedule_with_arguments_is_created(admin_client: Client) -> None:
    data = VALID_CRON | {
        "name": "mail",
        "task_path": "sampleapp.tasks.send_email",
        "task_args": "[3]",
        "task_kwargs": '{"subject": "hi"}',
        "trigger_kind": "interval",
        "cron": "",
        "timezone": "",
        "every": "15m",
    }
    assert admin_client.post(ADD, data).status_code == 302
    created = store().get_schedule("mail")
    assert created is not None
    assert isinstance(created.definition.trigger, IntervalTrigger)
    assert created.definition.trigger.every.total_seconds() == 900
    assert created.definition.task == TaskCall(
        "sampleapp.tasks.send_email", (3,), {"subject": "hi"}
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cron", "61 * * * *"),
        ("timezone", "Mars/Base"),
        ("task_path", "sampleapp.tasks.missing"),
        ("task_path", "sampleapp.tasks.RUNS"),
        ("max_catch_up", "0"),
    ],
)
def test_invalid_input_is_a_form_error(admin_client: Client, field: str, value: str) -> None:
    response = admin_client.post(ADD, VALID_CRON | {field: value})
    assert response.status_code == 200
    assert b"errorlist" in response.content
    assert store().get_schedule("nightly") is None


def test_an_interval_needs_a_valid_duration(admin_client: Client) -> None:
    data = VALID_CRON | {"trigger_kind": "interval", "cron": "", "every": "soon"}
    assert admin_client.post(ADD, data).status_code == 200
    assert store().get_schedule("nightly") is None


def test_a_code_schedule_only_accepts_enabled_changes(admin_client: Client) -> None:
    url = f"{CHANGELIST}{schedule_id('ping')}/change/"
    page = admin_client.get(url)
    assert page.status_code == 200
    assert b'name="cron"' not in page.content
    assert b'name="enabled"' in page.content
    inline = {"executions-TOTAL_FORMS": "0", "executions-INITIAL_FORMS": "0"}
    assert admin_client.post(url, {"cron": "* * * * *"} | inline).status_code == 302
    ping = store().get_schedule("ping")
    assert ping is not None
    assert not ping.definition.enabled
    assert isinstance(ping.definition.trigger, IntervalTrigger)


def test_actions_disable_enable_and_request_runs(admin_client: Client) -> None:
    selected = [schedule_id("ping")]
    admin_client.post(CHANGELIST, {"action": "disable_schedules", "_selected_action": selected})
    ping = store().get_schedule("ping")
    assert ping is not None
    assert not ping.definition.enabled
    admin_client.post(CHANGELIST, {"action": "enable_schedules", "_selected_action": selected})
    admin_client.post(CHANGELIST, {"action": "run_schedules_now", "_selected_action": selected})
    [requested] = store().recent_executions(None, limit=1)
    assert requested.status is ExecutionStatus.REQUESTED
    assert requested.scheduler_id.value == "admin:admin"


def test_executions_are_read_only(admin_client: Client) -> None:
    ping = store().get_schedule("ping")
    assert ping is not None
    store().request_run(ping, IdempotencyKey("manual:x"), SchedulerId("t"), SystemClock().now())
    listing = admin_client.get("/admin/goatbeat/execution/")
    assert listing.status_code == 200
    assert b"manual:x" in listing.content
    assert admin_client.get("/admin/goatbeat/execution/add/").status_code == 403


def test_editing_a_store_schedule_updates_it_through_the_store(admin_client: Client) -> None:
    assert admin_client.post(ADD, VALID_CRON).status_code == 302
    created = store().get_schedule("nightly")
    assert created is not None
    url = f"{CHANGELIST}{created.id.value}/change/"
    inline = {"executions-TOTAL_FORMS": "0", "executions-INITIAL_FORMS": "0"}
    edited = VALID_CRON | {"cron": "30 4 * * *"} | inline
    response = admin_client.post(url, edited)
    assert response.status_code == 302, response.content
    updated = store().get_schedule("nightly")
    assert updated is not None
    assert updated.id == created.id
    assert isinstance(updated.definition.trigger, CronTrigger)
    assert updated.definition.trigger.expression.text == "30 4 * * *"
    assert updated.next_run_at == updated.definition.trigger.next_after(SystemClock().now())
    disabled = edited | {"cron": "30 4 * * *"}
    del disabled["enabled"]
    assert admin_client.post(url, disabled).status_code == 302
    paused = store().get_schedule("nightly")
    assert paused is not None
    assert not paused.definition.enabled
