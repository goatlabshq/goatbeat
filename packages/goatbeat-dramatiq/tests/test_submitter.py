from collections.abc import Iterator
from datetime import UTC, datetime
from typing import cast

import pytest
from dramatiq import Message
from dramatiq_actors import broker

from goatbeat.core.errors import SubmissionError
from goatbeat.core.ids import IdempotencyKey, ScheduleId
from goatbeat.core.schedule import Routing
from goatbeat.core.submission import TaskSubmission
from goatbeat.core.tasks import TaskCall
from goatbeat.core.time import Instant
from goatbeat.dramatiq import DramatiqSubmitter

KEY = IdempotencyKey("s:2026-01-01T00:00:00+00:00")


def submission(
    path: str = "dramatiq_actors.send_email", routing: Routing | None = None
) -> TaskSubmission:
    return TaskSubmission(
        schedule_id=ScheduleId("s"),
        schedule_name="job",
        scheduled_at=Instant.of(datetime(2026, 1, 1, tzinfo=UTC)),
        idempotency_key=KEY,
        task=TaskCall(path, (42,), {"subject": "hi"}),
        routing=routing or Routing(),
    )


def decode(data: bytes) -> Message[object]:
    return cast("Message[object]", Message.decode(data))  # pyright: ignore[reportUnknownMemberType]


@pytest.fixture(autouse=True)
def _flush() -> Iterator[None]:
    broker.flush_all()
    yield
    broker.flush_all()


def test_the_idempotency_key_is_the_message_id() -> None:
    receipt = DramatiqSubmitter().submit(submission())
    [message] = [broker.queues["default"].get_nowait()]
    decoded = decode(message)
    assert receipt.result_id == KEY.value
    assert decoded.message_id == KEY.value
    assert decoded.actor_name == "send_email"
    assert (decoded.args, decoded.kwargs) == ((42,), {"subject": "hi"})


def test_the_queue_is_routed() -> None:
    broker.declare_queue("low")
    DramatiqSubmitter().submit(submission(routing=Routing(queue="low")))
    assert decode(broker.queues["low"].get_nowait()).queue_name == "low"


def test_priority_is_rejected_on_brokers_that_ignore_it() -> None:
    with pytest.raises(SubmissionError, match="RabbitMQ"):
        DramatiqSubmitter().submit(submission(routing=Routing(priority=3)))


def test_resubmitting_reuses_the_message_id() -> None:
    submitter = DramatiqSubmitter()
    submitter.submit(submission())
    submitter.submit(submission())
    queue = broker.queues["default"]
    ids = {decode(queue.get_nowait()).message_id, decode(queue.get_nowait()).message_id}
    assert ids == {KEY.value}


@pytest.mark.parametrize(
    ("path", "routing"),
    [
        ("dramatiq_actors.missing", Routing()),
        ("dramatiq_actors.NOT_AN_ACTOR", Routing()),
        ("dramatiq_actors.send_email", Routing(backend="other")),
    ],
)
def test_submission_problems_are_submission_errors(path: str, routing: Routing) -> None:
    with pytest.raises(SubmissionError):
        DramatiqSubmitter().submit(submission(path, routing))
