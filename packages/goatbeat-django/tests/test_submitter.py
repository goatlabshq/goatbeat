from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from django.db import connection
from django.tasks import TaskResultStatus, task_backends
from django.tasks.backends.dummy import DummyBackend
from django.tasks.signals import task_finished
from sampleapp import tasks

from goatbeat.core.errors import SubmissionError
from goatbeat.core.execution import ExecutionStatus
from goatbeat.core.ids import IdempotencyKey, ScheduleId
from goatbeat.core.schedule import Routing
from goatbeat.core.submission import TaskSubmission
from goatbeat.core.tasks import TaskCall
from goatbeat.core.testing import FakeClock
from goatbeat.core.testing.conformance import ALICE, TTL, every_minute, one_claim
from goatbeat.core.time import Instant
from goatbeat.django.provider import DjangoProvider
from goatbeat.django.submitter import DjangoTasksSubmitter
from goatbeat.postgres.store import PostgresStore

# The completion receiver writes to the database whenever a task finishes, even inline.
pytestmark = pytest.mark.django_db(transaction=True)

KEY = IdempotencyKey("s:2026-01-01T00:00:00+00:00")


def submission(task: TaskCall, routing: Routing | None = None) -> TaskSubmission:
    return TaskSubmission(
        schedule_id=ScheduleId("s"),
        schedule_name="job",
        scheduled_at=Instant.of(datetime(2026, 1, 1, tzinfo=UTC)),
        idempotency_key=KEY,
        task=task,
        routing=routing or Routing(),
    )


@pytest.fixture
def dummy() -> Iterator[DummyBackend]:
    backend = task_backends["dummy"]
    assert isinstance(backend, DummyBackend)
    backend.clear()
    yield backend
    backend.clear()


@pytest.fixture(autouse=True)
def _runs() -> None:
    tasks.RUNS.clear()


def test_an_immediate_backend_reports_the_outcome_with_the_receipt() -> None:
    receipt = DjangoTasksSubmitter().submit(submission(TaskCall("sampleapp.tasks.send_report")))
    assert tasks.RUNS == ["report"]
    assert receipt.result_id
    assert receipt.outcome is ExecutionStatus.COMPLETED


def test_a_failing_task_is_reported_as_task_failed() -> None:
    receipt = DjangoTasksSubmitter().submit(submission(TaskCall("sampleapp.tasks.explode")))
    assert receipt.outcome is ExecutionStatus.TASK_FAILED


def test_arguments_and_the_idempotency_key_are_passed() -> None:
    submitter = DjangoTasksSubmitter()
    submitter.submit(submission(TaskCall("sampleapp.tasks.send_email", (7,), {"subject": "x"})))
    submitter.submit(submission(TaskCall("sampleapp.tasks.keyed")))
    assert ["email:7:x", f"keyed:{KEY.value}"] == tasks.RUNS


def test_routing_is_applied_and_queued_tasks_stay_dispatched(dummy: DummyBackend) -> None:
    routing = Routing(queue="low", priority=-5, backend="dummy")
    receipt = DjangoTasksSubmitter().submit(
        submission(TaskCall("sampleapp.tasks.send_report"), routing)
    )
    [queued] = dummy.results
    assert (queued.task.queue_name, queued.task.priority) == ("low", -5)
    assert queued.id == receipt.result_id
    assert receipt.outcome is None


@pytest.mark.parametrize(
    ("path", "routing"),
    [
        ("sampleapp.tasks.missing", Routing()),
        ("sampleapp.tasks.RUNS", Routing()),
        ("sampleapp.tasks.send_report", Routing(queue="unknown-queue")),
        ("sampleapp.tasks.send_report", Routing(backend="unknown-backend")),
    ],
)
def test_submission_problems_are_submission_errors(path: str, routing: Routing) -> None:
    with pytest.raises(SubmissionError):
        DjangoTasksSubmitter().submit(submission(TaskCall(path), routing))


def test_a_task_finishing_later_completes_its_execution(dummy: DummyBackend) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO goatbeat_lease VALUES (0, NULL, 0, '-infinity') ON CONFLICT DO NOTHING"
        )
    clock = FakeClock()
    store = PostgresStore(DjangoProvider(), lease_clock=clock)
    schedule = store.save_schedule(every_minute("job", clock), clock.now())
    lease = store.acquire(ALICE, TTL)
    assert lease is not None
    [execution] = store.claim(lease, schedule, one_claim(schedule), clock.now())
    receipt = DjangoTasksSubmitter().submit(
        submission(TaskCall("sampleapp.tasks.send_report"), Routing(backend="dummy"))
    )
    store.mark_dispatched(execution.idempotency_key, clock.now(), receipt)
    [queued] = dummy.results
    finished = replace(queued, status=TaskResultStatus.SUCCESSFUL, finished_at=datetime.now(UTC))
    task_finished.send(type(dummy), task_result=finished)
    [stored] = store.recent_executions(schedule.id, limit=1)
    assert stored.status is ExecutionStatus.COMPLETED
    assert stored.completed_at is not None


def test_bookkeeping_errors_never_fail_an_enqueue(caplog: pytest.LogCaptureFixture) -> None:
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE goatbeat_execution RENAME TO goatbeat_execution_hidden")
    try:
        tasks.send_report.enqueue()
    finally:
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE goatbeat_execution_hidden RENAME TO goatbeat_execution")
    assert tasks.RUNS == ["report"]
    assert "store.unavailable" in caplog.text
