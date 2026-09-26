"""The seams of the scheduler: every backend implements these protocols."""

from collections.abc import Sequence
from datetime import timedelta
from typing import Protocol

from goatbeat.core.execution import Execution, Lease, SubmissionReceipt
from goatbeat.core.ids import IdempotencyKey, ScheduleId, SchedulerId
from goatbeat.core.misfire import OccurrencePlan
from goatbeat.core.schedule import Schedule, ScheduleDefinition
from goatbeat.core.submission import PendingSubmission, TaskSubmission
from goatbeat.core.time import Instant


class LeaseManager(Protocol):
    def acquire(self, holder: SchedulerId, ttl: timedelta) -> Lease | None:
        """Acquire or renew; the token only changes when the holder changes."""
        ...

    def release(self, lease: Lease) -> None: ...


class ScheduleStore(Protocol):
    def sync_code_schedules(
        self, definitions: Sequence[ScheduleDefinition], now: Instant, *, prune: bool = False
    ) -> None:
        """Upsert code-declared schedules; ``prune`` disables code schedules not listed."""
        ...

    def save_schedule(self, definition: ScheduleDefinition, now: Instant) -> Schedule: ...

    def get_schedule(self, name: str) -> Schedule | None: ...

    def list_schedules(self) -> Sequence[Schedule]: ...

    def set_enabled(self, name: str, *, enabled: bool, now: Instant) -> None: ...

    def due_schedules(self, now: Instant, limit: int) -> Sequence[Schedule]: ...

    def claim(
        self, lease: Lease, schedule: Schedule, plan: OccurrencePlan, now: Instant
    ) -> Sequence[Execution]:
        """Atomically fence-check, insert new executions and advance the schedule."""
        ...

    def request_run(
        self, schedule: Schedule, key: IdempotencyKey, requested_by: SchedulerId, now: Instant
    ) -> Execution:
        """Ask the leader to dispatch now; needs no lease, so any process can call it."""
        ...

    def pending_submissions(
        self, now: Instant, stale_before: Instant, limit: int
    ) -> Sequence[PendingSubmission]: ...

    def mark_dispatched(
        self, key: IdempotencyKey, at: Instant, receipt: SubmissionReceipt
    ) -> None: ...

    def mark_submit_failed(
        self, key: IdempotencyKey, error: str, retry_at: Instant | None
    ) -> None: ...

    def record_completion(self, result_id: str, *, succeeded: bool, at: Instant) -> bool:
        """Finish a dispatched execution by its backend result id; False if none matched."""
        ...

    def next_wakeup(self) -> Instant | None: ...

    def recent_executions(
        self, schedule_id: ScheduleId | None, limit: int
    ) -> Sequence[Execution]: ...

    def wait_for_change(self, timeout: timedelta) -> bool: ...


class TaskSubmitter(Protocol):
    def submit(self, submission: TaskSubmission) -> SubmissionReceipt:
        """Hand the task to the backend; raise SubmissionError on failure."""
        ...
