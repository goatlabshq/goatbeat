"""Submits scheduled occurrences as Django Tasks."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Final

from django.tasks import Task, TaskResultStatus
from django.tasks.exceptions import InvalidTask, InvalidTaskBackend
from django.utils.module_loading import import_string

from goatbeat.core.errors import SubmissionError
from goatbeat.core.execution import ExecutionStatus, SubmissionReceipt, TaskOutcome

if TYPE_CHECKING:
    from goatbeat.core.json import JsonValue
    from goatbeat.core.submission import TaskSubmission

KEY_PARAMETER: Final = "goatbeat_key"
_OUTCOMES: Final[dict[TaskResultStatus, TaskOutcome]] = {
    TaskResultStatus.SUCCESSFUL: ExecutionStatus.COMPLETED,
    TaskResultStatus.FAILED: ExecutionStatus.TASK_FAILED,
}


class DjangoTasksSubmitter:
    """Enqueues through ``Task.using(...).enqueue``; a task declaring ``goatbeat_key`` gets it."""

    def submit(self, submission: TaskSubmission) -> SubmissionReceipt:
        task = _resolve(submission.task.path)
        routing = submission.routing
        kwargs: dict[str, JsonValue] = dict(submission.task.kwargs)
        if KEY_PARAMETER in inspect.signature(task.func).parameters:
            kwargs[KEY_PARAMETER] = submission.idempotency_key.value
        try:
            routed = task.using(
                queue_name=routing.queue, priority=routing.priority, backend=routing.backend
            )
            result = routed.enqueue(*submission.task.args, **kwargs)
        except (InvalidTask, InvalidTaskBackend) as error:
            raise SubmissionError(str(error)) from error
        # Immediate backends run the task inside enqueue, before the dispatch is recorded.
        return SubmissionReceipt(result.id, outcome=_OUTCOMES.get(result.status))


def _resolve(path: str) -> Task[..., object]:
    try:
        target: object = import_string(path)
    except ImportError as error:
        raise SubmissionError(f"no Django task at {path!r}") from error
    if not isinstance(target, Task):
        raise SubmissionError(f"{path!r} is not a django.tasks.Task")
    return target  # pyright: ignore[reportUnknownVariableType]
