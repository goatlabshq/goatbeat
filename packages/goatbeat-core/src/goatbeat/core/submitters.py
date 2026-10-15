import logging
from concurrent.futures import Future, ThreadPoolExecutor
from types import TracebackType
from typing import Self

from goatbeat.core.errors import SubmissionError, TaskNotFoundError
from goatbeat.core.execution import SubmissionReceipt
from goatbeat.core.observability import LOGGER_NAME
from goatbeat.core.schedule import Routing
from goatbeat.core.submission import TaskSubmission
from goatbeat.core.tasks import import_task


class CallableSubmitter:
    """Runs tasks in-process. Nothing survives a crash: use a real task backend in production."""

    def __init__(self, max_workers: int = 4, logger: logging.Logger | None = None) -> None:
        self._executor = ThreadPoolExecutor(max_workers, thread_name_prefix="goatbeat-task")
        self._logger = logger or logging.getLogger(LOGGER_NAME)

    def submit(self, submission: TaskSubmission) -> SubmissionReceipt:
        if submission.routing != Routing():
            raise SubmissionError("the callable submitter supports no routing options")
        try:
            task = import_task(submission.task.path)
        except TaskNotFoundError as error:
            raise SubmissionError(str(error)) from error
        future = self._executor.submit(task, *submission.task.args, **submission.task.kwargs)
        future.add_done_callback(lambda done: self._report(submission, done))
        return SubmissionReceipt(submission.idempotency_key.value)

    def close(self) -> None:
        self._executor.shutdown(wait=True)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _report(self, submission: TaskSubmission, done: Future[object]) -> None:
        error = done.exception()
        if error is not None:
            self._logger.error("task %s failed", submission.idempotency_key.value, exc_info=error)
