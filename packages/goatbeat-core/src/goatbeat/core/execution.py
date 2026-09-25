"""Execution history types shared by stores, submitters and the scheduler."""

from enum import StrEnum


class ExecutionStatus(StrEnum):
    CLAIMED = "claimed"
    DISPATCHED = "dispatched"
    SUBMIT_FAILED = "submit_failed"
    FAILED = "failed"
    SKIPPED = "skipped"
    COMPLETED = "completed"
    TASK_FAILED = "task_failed"
