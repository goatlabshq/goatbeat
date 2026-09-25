from datetime import UTC, datetime

import pytest
import sample_tasks

from goatbeat.core.errors import SubmissionError
from goatbeat.core.ids import IdempotencyKey, ScheduleId
from goatbeat.core.schedule import Routing
from goatbeat.core.submission import TaskSubmission
from goatbeat.core.submitters import CallableSubmitter
from goatbeat.core.tasks import TaskCall
from goatbeat.core.time import Instant


def submission(task: TaskCall) -> TaskSubmission:
    return TaskSubmission(
        schedule_id=ScheduleId("s"),
        schedule_name="job",
        scheduled_at=Instant.of(datetime(2026, 1, 1, tzinfo=UTC)),
        idempotency_key=IdempotencyKey("s:2026"),
        task=task,
        routing=Routing(),
    )


def test_runs_the_task_with_its_arguments() -> None:
    sample_tasks.CALLS.clear()
    with CallableSubmitter() as submitter:
        receipt = submitter.submit(
            submission(TaskCall("sample_tasks.send_email", (7,), {"subject": "hi"}))
        )
    assert receipt.result_id == "s:2026"
    assert sample_tasks.CALLS == [("send_email", 7, "hi")]


def test_unknown_task_is_a_submission_error() -> None:
    with CallableSubmitter() as submitter, pytest.raises(SubmissionError):
        submitter.submit(submission(TaskCall("sample_tasks.missing")))


def test_routing_options_are_rejected() -> None:
    with CallableSubmitter() as submitter, pytest.raises(SubmissionError):
        submitter.submit(
            TaskSubmission(
                schedule_id=ScheduleId("s"),
                schedule_name="job",
                scheduled_at=Instant.of(datetime(2026, 1, 1, tzinfo=UTC)),
                idempotency_key=IdempotencyKey("k"),
                task=TaskCall("sample_tasks.generate_report"),
                routing=Routing(queue="high"),
            )
        )
