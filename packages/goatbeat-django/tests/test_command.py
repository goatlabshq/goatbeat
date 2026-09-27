import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db import connection
from sampleapp import tasks

from goatbeat.cli.main import main
from goatbeat.core.execution import ExecutionStatus
from goatbeat.core.schedule import ScheduleSource
from goatbeat.core.tasks import TaskCall
from goatbeat.core.testing import FakeClock
from goatbeat.core.testing.conformance import every_minute
from goatbeat.core.time import SystemClock
from goatbeat.django.provider import DjangoProvider
from goatbeat.postgres.store import PostgresStore

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _lease_row() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO goatbeat_lease VALUES (0, NULL, 0, '-infinity') ON CONFLICT DO NOTHING"
        )
    tasks.RUNS.clear()


def goatbeat(*arguments: str) -> str:
    output = StringIO()
    call_command("goatbeat", *arguments, stdout=output)
    return output.getvalue()


def store() -> PostgresStore:
    return PostgresStore(DjangoProvider())


def test_list_publishes_code_schedules_and_prints_json() -> None:
    listed = json.loads(goatbeat("schedule", "list", "--json"))
    assert [item["name"] for item in listed] == ["daily-report", "ping"]
    ping = listed[1]
    assert ping["source"] == "code"
    assert ping["enabled"] is True
    assert ping["trigger"] == "every 0:05:00"
    assert ping["next_run_at"].endswith("+00:00")


def test_list_prints_a_table_by_default() -> None:
    assert "daily-report" in goatbeat("schedule", "list")


def test_run_requests_an_extra_run_that_the_scheduler_dispatches() -> None:
    goatbeat("schedule", "list")
    assert "requested" in goatbeat("schedule", "run", "daily-report")
    goatbeat("scheduler", "--once")
    assert tasks.RUNS == ["report"]
    [execution] = store().recent_executions(None, limit=1)
    assert execution.status is ExecutionStatus.COMPLETED
    assert execution.idempotency_key.value.startswith("manual:")


def test_running_an_unknown_schedule_fails() -> None:
    with pytest.raises(CommandError, match="nope"):
        goatbeat("schedule", "run", "nope")


def test_prune_disables_code_schedules_no_longer_declared() -> None:
    clock = FakeClock(SystemClock().now())
    removed = every_minute("removed", clock, task="sampleapp.tasks.send_report")
    store().sync_code_schedules([removed], clock.now())
    goatbeat("schedule", "prune")
    pruned = store().get_schedule("removed")
    assert pruned is not None
    assert pruned.source is ScheduleSource.CODE
    assert not pruned.definition.enabled
    assert pruned.definition.task == TaskCall("sampleapp.tasks.send_report")
    assert store().get_schedule("ping") is not None


def test_the_standalone_cli_uses_the_django_project(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Any importable module: the test harness has already configured the settings.
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "sampleapp.urls")
    monkeypatch.delenv("GOATBEAT_APP", raising=False)
    assert main(["schedule", "list", "--json"]) == 0
    names = [item["name"] for item in json.loads(capsys.readouterr().out)]
    assert names == ["daily-report", "ping"]
    assert main(["doctor", "--json"]) == 0
    checks = {check["name"]: check["ok"] for check in json.loads(capsys.readouterr().out)}
    assert checks == {"store": True, "tasks": True}
