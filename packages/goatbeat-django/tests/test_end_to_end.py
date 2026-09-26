import threading
from datetime import timedelta

import pytest
from django.db import connection
from sampleapp import tasks

from goatbeat.core.execution import ExecutionStatus
from goatbeat.core.scheduler import Scheduler
from goatbeat.core.testing import FakeClock
from goatbeat.core.time import SystemClock
from goatbeat.django import registry
from goatbeat.django.conf import DjangoSettings
from goatbeat.django.provider import DjangoProvider
from goatbeat.django.runtime import scheduler
from goatbeat.django.submitter import DjangoTasksSubmitter
from goatbeat.postgres.store import PostgresStore

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _lease_row() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO goatbeat_lease VALUES (0, NULL, 0, '-infinity') ON CONFLICT DO NOTHING"
        )
    tasks.RUNS.clear()


def test_a_declared_schedule_runs_through_django_tasks_and_completes() -> None:
    clock = FakeClock(SystemClock().now())
    store = PostgresStore(DjangoProvider(), lease_clock=clock)
    running = Scheduler(
        store=store,
        leases=store,
        submitter=DjangoTasksSubmitter(),
        config=DjangoSettings.from_django().config,
        registry=registry(),
        clock=clock,
    )
    running.start()
    ping = store.get_schedule("ping")
    assert ping is not None
    clock.set(ping.next_run_at + timedelta(seconds=1))
    running.tick()
    assert tasks.RUNS == ["email:42:ping"]
    [execution] = store.recent_executions(ping.id, limit=5)
    assert execution.status is ExecutionStatus.COMPLETED
    assert execution.backend_result_id is not None


def test_the_runtime_listens_on_the_django_database(caplog: pytest.LogCaptureFixture) -> None:
    with scheduler() as running:
        running.start()
        running.tick()
        assert running.is_leader
        running.sleep_until(SystemClock().now() + timedelta(milliseconds=200), threading.Event())
    # The notifier degrades to polling with a warning when it cannot LISTEN.
    assert "store.unavailable" not in caplog.text
