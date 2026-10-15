from kombu.exceptions import KombuError, OperationalError

from celery import Celery
from goatbeat.core.errors import SubmissionError
from goatbeat.core.execution import SubmissionReceipt
from goatbeat.core.submission import TaskSubmission


class CelerySubmitter:
    """The task path is the Celery task name (Celery's default for ``@app.task``)."""

    def __init__(self, app: Celery) -> None:
        self._app = app

    def submit(self, submission: TaskSubmission) -> SubmissionReceipt:
        routing = submission.routing
        if routing.backend is not None:
            raise SubmissionError("Celery has no task backends to choose from; route by queue")
        try:
            self._app.send_task(
                submission.task.path,
                args=list(submission.task.args),
                kwargs=dict(submission.task.kwargs),
                task_id=submission.idempotency_key.value,
                queue=routing.queue,
                priority=routing.priority,
            )
        except (KombuError, OperationalError, OSError) as error:
            raise SubmissionError(f"Celery broker refused the task: {error}") from error
        return SubmissionReceipt(submission.idempotency_key.value)
