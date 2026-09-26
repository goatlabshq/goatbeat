from collections.abc import Iterator
from datetime import timedelta

import pytest

from goatbeat.core.config import GoatbeatConfig
from goatbeat.core.errors import SubmissionError
from goatbeat.core.execution import ExecutionStatus, SubmissionReceipt
from goatbeat.core.ids import SchedulerId
from goatbeat.core.registry import Registry
from goatbeat.core.scheduler import Scheduler
from goatbeat.core.submission import TaskSubmission
from goatbeat.core.testing import FakeClock
from goatbeat.postgres.provider import PsycopgProvider
from goatbeat.postgres.schema import migrate
from goatbeat.postgres.store import PostgresStore


def report() -> None: ...


class FlakyBackend:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.accepted: list[str] = []

    def submit(self, submission: TaskSubmission) -> SubmissionReceipt:
        if self.failures:
            self.failures -= 1
            raise SubmissionError("backend unavailable")
        self.accepted.append(submission.idempotency_key.value)
        return SubmissionReceipt("task-1")


@pytest.fixture
def provider(conninfo: str) -> Iterator[PsycopgProvider]:
    with PsycopgProvider.connect(conninfo) as opened:
        migrate(opened)
        yield opened


def test_a_backend_failure_is_recorded_then_retried_until_dispatched(
    provider: PsycopgProvider,
) -> None:
    clock = FakeClock()
    store = PostgresStore(provider, lease_clock=clock)
    backend = FlakyBackend(failures=2)
    registry = Registry()
    registry.schedule(name="report", task=report, every="1m")
    scheduler = Scheduler(
        store=store,
        leases=store,
        submitter=backend,
        config=GoatbeatConfig(scheduler_id=SchedulerId("alice")),
        registry=registry,
        clock=clock,
    )
    scheduler.start()
    clock.advance(timedelta(minutes=1))
    scheduler.tick()
    [failed] = store.recent_executions(None, limit=1)
    assert failed.status is ExecutionStatus.SUBMIT_FAILED
    assert failed.error == "backend unavailable"
    clock.advance(timedelta(seconds=5))
    scheduler.tick()
    clock.advance(timedelta(seconds=10))
    scheduler.tick()
    [dispatched] = store.recent_executions(None, limit=1)
    assert dispatched.status is ExecutionStatus.DISPATCHED
    assert dispatched.retry_count == 2
    assert dispatched.backend_result_id == "task-1"
    assert backend.accepted == [dispatched.idempotency_key.value]
