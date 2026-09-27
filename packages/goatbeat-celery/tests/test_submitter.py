from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from celery import Celery
from kombu import Message

from goatbeat.celery import CelerySubmitter
from goatbeat.core.errors import SubmissionError
from goatbeat.core.ids import IdempotencyKey, ScheduleId
from goatbeat.core.schedule import Routing
from goatbeat.core.submission import TaskSubmission
from goatbeat.core.tasks import TaskCall
from goatbeat.core.time import Instant

KEY = IdempotencyKey("s:2026-01-01T00:00:00+00:00")


def submission(routing: Routing | None = None) -> TaskSubmission:
    return TaskSubmission(
        schedule_id=ScheduleId("s"),
        schedule_name="job",
        scheduled_at=Instant.of(datetime(2026, 1, 1, tzinfo=UTC)),
        idempotency_key=KEY,
        task=TaskCall("app.tasks.send_email", (42,), {"subject": "hi"}),
        routing=routing or Routing(),
    )


@pytest.fixture
def app() -> Iterator[Celery]:
    celery = Celery("tests", broker="memory://", set_as_current=False)
    yield celery
    celery.close()


def published(app: Celery, queue: str) -> Message:
    with app.connection_for_read() as connection:
        simple = connection.SimpleQueue(queue)
        message = simple.get(timeout=2)
        message.ack()
        simple.close()
        return message


def test_the_idempotency_key_is_the_celery_task_id(app: Celery) -> None:
    receipt = CelerySubmitter(app).submit(submission(Routing(queue="low", priority=5)))
    message = published(app, "low")
    assert receipt.result_id == KEY.value
    assert message.headers["id"] == KEY.value
    assert message.headers["task"] == "app.tasks.send_email"
    args, kwargs, _ = message.decode()
    assert (args, kwargs) == ([42], {"subject": "hi"})
    assert message.properties["priority"] == 5


def test_resubmitting_reuses_the_task_id(app: Celery) -> None:
    submitter = CelerySubmitter(app)
    submitter.submit(submission())
    submitter.submit(submission())
    assert published(app, "celery").headers["id"] == KEY.value
    assert published(app, "celery").headers["id"] == KEY.value


def test_a_backend_routing_option_is_rejected(app: Celery) -> None:
    with pytest.raises(SubmissionError):
        CelerySubmitter(app).submit(submission(Routing(backend="other")))


def test_a_broker_failure_is_a_submission_error() -> None:
    broken = Celery("tests", broker="amqp://nobody@127.0.0.1:1//", set_as_current=False)
    broken.conf.broker_connection_retry = False
    broken.conf.broker_connection_max_retries = 0
    broken.conf.broker_transport_options = {"max_retries": 0}
    with pytest.raises(SubmissionError):
        CelerySubmitter(broken).submit(submission())
    broken.close()
