"""Execution history types shared by stores, submitters and the scheduler."""

from dataclasses import dataclass
from enum import StrEnum

from goatbeat.core.ids import FencingToken, IdempotencyKey, ScheduleId, SchedulerId
from goatbeat.core.time import Instant


class ExecutionStatus(StrEnum):
    CLAIMED = "claimed"
    DISPATCHED = "dispatched"
    SUBMIT_FAILED = "submit_failed"
    FAILED = "failed"
    SKIPPED = "skipped"
    COMPLETED = "completed"
    TASK_FAILED = "task_failed"


@dataclass(frozen=True, slots=True)
class Lease:
    holder: SchedulerId
    token: FencingToken


@dataclass(frozen=True, slots=True)
class Execution:
    schedule_id: ScheduleId
    scheduled_at: Instant
    idempotency_key: IdempotencyKey
    status: ExecutionStatus
    scheduler_id: SchedulerId
    fencing_token: FencingToken
    claimed_at: Instant
    missed_count: int = 0
    retry_count: int = 0
    dispatched_at: Instant | None = None
    completed_at: Instant | None = None
    next_retry_at: Instant | None = None
    backend_result_id: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SubmissionReceipt:
    result_id: str | None = None


def idempotency_key_for(schedule_id: ScheduleId, scheduled_at: Instant) -> IdempotencyKey:
    return IdempotencyKey(f"{schedule_id.value}:{scheduled_at.isoformat()}")
