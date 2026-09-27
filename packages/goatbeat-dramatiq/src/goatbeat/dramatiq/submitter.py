"""Enqueues scheduled occurrences as Dramatiq messages whose id is the idempotency key."""

from typing import Final, Protocol, Self, cast

from dramatiq import Actor
from dramatiq.errors import DramatiqError
from goatbeat.core.errors import SubmissionError, TaskNotFoundError
from goatbeat.core.execution import SubmissionReceipt
from goatbeat.core.submission import TaskSubmission
from goatbeat.core.tasks import import_task

# Compared by name so the RabbitMQ client (pika) is never imported for the check.
RABBITMQ_BROKER: Final = "RabbitmqBroker"


class _Message(Protocol):
    @property
    def queue_name(self) -> str: ...

    def copy(self, **attributes: object) -> Self: ...


class _Broker(Protocol):
    def get_declared_queues(self) -> set[str]: ...

    def declare_queue(self, queue_name: str) -> None: ...

    def enqueue(self, message: _Message) -> object: ...


class _Actor(Protocol):
    """The part of ``dramatiq.Actor`` used here; Dramatiq leaves its message types unknown."""

    queue_name: str
    broker: _Broker

    def message_with_options(
        self, *, args: tuple[object, ...], kwargs: dict[str, object], **options: object
    ) -> _Message: ...


class DramatiqSubmitter:
    """Resolves the actor by import path and sends it through the actor's own broker."""

    def submit(self, submission: TaskSubmission) -> SubmissionReceipt:
        routing = submission.routing
        if routing.backend is not None:
            raise SubmissionError("an actor is bound to one broker; route by queue")
        actor = _resolve(submission.task.path)
        options: dict[str, object] = {}
        if routing.priority is not None:
            if type(actor.broker).__name__ != RABBITMQ_BROKER:
                raise SubmissionError("Dramatiq honors priorities on RabbitMQ brokers only")
            options["broker_priority"] = routing.priority
        message = actor.message_with_options(
            args=submission.task.args, kwargs=dict(submission.task.kwargs), **options
        ).copy(
            message_id=submission.idempotency_key.value,
            queue_name=routing.queue or actor.queue_name,
        )
        try:
            if message.queue_name not in actor.broker.get_declared_queues():
                actor.broker.declare_queue(message.queue_name)
            actor.broker.enqueue(message)
        except (DramatiqError, OSError) as error:
            raise SubmissionError(f"Dramatiq broker refused the message: {error}") from error
        return SubmissionReceipt(submission.idempotency_key.value)


def _resolve(path: str) -> _Actor:
    try:
        target: object = import_task(path)
    except TaskNotFoundError as error:
        raise SubmissionError(str(error)) from error
    if not isinstance(target, Actor):
        raise SubmissionError(f"{path!r} is not a Dramatiq actor")
    return cast("_Actor", target)
