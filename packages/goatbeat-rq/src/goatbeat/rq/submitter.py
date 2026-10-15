import hashlib
from typing import Final, Protocol, cast

from redis import Redis
from redis.exceptions import RedisError

from goatbeat.core.errors import SubmissionError
from goatbeat.core.execution import SubmissionReceipt
from goatbeat.core.ids import IdempotencyKey
from goatbeat.core.submission import TaskSubmission
from rq import Queue

DEFAULT_QUEUE: Final = "default"
JOB_ID_PREFIX: Final = "goatbeat-"


class _Queue(Protocol):
    """The typed subset of ``rq.Queue`` used here (RQ leaves some parameters unannotated)."""

    def enqueue_call(
        self,
        func: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
        *,
        job_id: str,
    ) -> object: ...


def job_id_for(key: IdempotencyKey) -> str:
    """RQ only accepts [A-Za-z0-9_-] in job ids, so the key is hashed, deterministically."""
    return JOB_ID_PREFIX + hashlib.sha256(key.value.encode()).hexdigest()


class RQSubmitter:
    def __init__(self, connection: Redis) -> None:
        self._connection = connection

    def submit(self, submission: TaskSubmission) -> SubmissionReceipt:
        routing = submission.routing
        if routing.priority is not None or routing.backend is not None:
            raise SubmissionError("RQ supports queue routing only (no priority, no backend)")
        job_id = job_id_for(submission.idempotency_key)
        queue = cast("_Queue", Queue(routing.queue or DEFAULT_QUEUE, connection=self._connection))
        try:
            queue.enqueue_call(
                func=submission.task.path,
                args=submission.task.args,
                kwargs=dict(submission.task.kwargs),
                job_id=job_id,
            )
        except RedisError as error:
            raise SubmissionError(f"RQ could not enqueue the job: {error}") from error
        return SubmissionReceipt(job_id)
