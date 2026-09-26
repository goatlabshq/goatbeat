"""In-process store for tests and single-process development; nothing survives a restart."""

import threading
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import timedelta

from goatbeat.core.errors import ConfigurationError, LeaseLostError
from goatbeat.core.execution import (
    Execution,
    ExecutionStatus,
    Lease,
    SubmissionReceipt,
    idempotency_key_for,
)
from goatbeat.core.ids import FencingToken, IdempotencyKey, ScheduleId, SchedulerId, new_schedule_id
from goatbeat.core.misfire import OccurrencePlan
from goatbeat.core.schedule import Schedule, ScheduleDefinition, ScheduleSource
from goatbeat.core.submission import PendingSubmission
from goatbeat.core.time import Clock, Instant

_NO_TOKEN = FencingToken(0)


@dataclass(slots=True)
class _LeaseRow:
    holder: SchedulerId | None = None
    token: FencingToken = _NO_TOKEN
    expires_at: Instant | None = None


class MemoryStore:
    """Implements both ScheduleStore and LeaseManager; lease time comes from ``clock``."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._changed = threading.Condition()
        self._lease = _LeaseRow()
        self._schedules: dict[str, Schedule] = {}
        self._executions: dict[IdempotencyKey, Execution] = {}

    # LeaseManager

    def acquire(self, holder: SchedulerId, ttl: timedelta) -> Lease | None:
        with self._changed:
            now = self._clock.now()
            row = self._lease
            if row.holder != holder and row.expires_at is not None and row.expires_at > now:
                return None
            if row.holder != holder:
                row.token = FencingToken(row.token.value + 1)
                row.holder = holder
            row.expires_at = now + ttl
            return Lease(holder, row.token)

    def release(self, lease: Lease) -> None:
        with self._changed:
            if self._holds(lease):
                self._lease.expires_at = self._clock.now()

    # ScheduleStore

    def sync_code_schedules(
        self, definitions: Sequence[ScheduleDefinition], now: Instant, *, prune: bool = False
    ) -> None:
        with self._changed:
            for definition in definitions:
                existing = self._schedules.get(definition.name)
                if existing is None:
                    self._insert(definition, ScheduleSource.CODE, now)
                else:
                    kept = replace(definition, enabled=existing.definition.enabled)
                    self._update(existing, kept, now)
            if prune:
                listed = {definition.name for definition in definitions}
                for schedule in list(self._schedules.values()):
                    if schedule.source is ScheduleSource.CODE and schedule.name not in listed:
                        self._set_enabled(schedule, enabled=False, now=now)
            self._changed.notify_all()

    def save_schedule(self, definition: ScheduleDefinition, now: Instant) -> Schedule:
        with self._changed:
            existing = self._schedules.get(definition.name)
            if existing is not None and existing.source is ScheduleSource.CODE:
                raise ConfigurationError(f"schedule {definition.name!r} is declared in code")
            if existing is None:
                saved = self._insert(definition, ScheduleSource.STORE, now)
            else:
                saved = self._update(existing, definition, now)
            self._changed.notify_all()
            return saved

    def get_schedule(self, name: str) -> Schedule | None:
        with self._changed:
            return self._schedules.get(name)

    def list_schedules(self) -> Sequence[Schedule]:
        with self._changed:
            return sorted(self._schedules.values(), key=lambda schedule: schedule.name)

    def set_enabled(self, name: str, *, enabled: bool, now: Instant) -> None:
        with self._changed:
            schedule = self._schedules.get(name)
            if schedule is None:
                raise ConfigurationError(f"unknown schedule {name!r}")
            self._set_enabled(schedule, enabled=enabled, now=now)
            self._changed.notify_all()

    def due_schedules(self, now: Instant, limit: int) -> Sequence[Schedule]:
        with self._changed:
            due = [
                schedule
                for schedule in self._schedules.values()
                if schedule.definition.enabled and schedule.next_run_at <= now
            ]
            return sorted(due, key=lambda schedule: schedule.next_run_at)[:limit]

    def claim(
        self, lease: Lease, schedule: Schedule, plan: OccurrencePlan, now: Instant
    ) -> Sequence[Execution]:
        with self._changed:
            self._ensure_fence(lease)
            created: list[Execution] = []
            for claim in plan.claims:
                key = idempotency_key_for(schedule.id, claim.scheduled_at)
                if key in self._executions:
                    continue
                execution = Execution(
                    schedule_id=schedule.id,
                    scheduled_at=claim.scheduled_at,
                    idempotency_key=key,
                    status=claim.status,
                    scheduler_id=lease.holder,
                    fencing_token=lease.token,
                    claimed_at=now,
                    missed_count=claim.missed_count,
                )
                self._executions[key] = execution
                created.append(execution)
            current = self._schedules.get(schedule.name)
            if current is not None and current.next_run_at == schedule.next_run_at:
                self._schedules[schedule.name] = replace(current, next_run_at=plan.next_run_at)
            return created

    def request_run(
        self, schedule: Schedule, key: IdempotencyKey, requested_by: SchedulerId, now: Instant
    ) -> Execution:
        with self._changed:
            execution = Execution(
                schedule_id=schedule.id,
                scheduled_at=now,
                idempotency_key=key,
                status=ExecutionStatus.REQUESTED,
                scheduler_id=requested_by,
                fencing_token=_NO_TOKEN,
                claimed_at=now,
            )
            self._executions.setdefault(key, execution)
            self._changed.notify_all()
            return self._executions[key]

    def pending_submissions(
        self, now: Instant, stale_before: Instant, limit: int
    ) -> Sequence[PendingSubmission]:
        with self._changed:
            by_id = {schedule.id: schedule for schedule in self._schedules.values()}
            pending = [
                PendingSubmission(execution, by_id[execution.schedule_id])
                for execution in self._executions.values()
                if execution.schedule_id in by_id and _is_pending(execution, now, stale_before)
            ]
            pending.sort(key=lambda item: item.execution.scheduled_at)
            return pending[:limit]

    def mark_dispatched(self, key: IdempotencyKey, at: Instant, receipt: SubmissionReceipt) -> None:
        with self._changed:
            execution = self._executions[key]
            self._executions[key] = replace(
                execution,
                status=receipt.status,
                dispatched_at=at,
                completed_at=None if receipt.outcome is None else at,
                backend_result_id=receipt.result_id,
                next_retry_at=None,
                error=None,
            )

    def mark_submit_failed(self, key: IdempotencyKey, error: str, retry_at: Instant | None) -> None:
        with self._changed:
            execution = self._executions[key]
            self._executions[key] = replace(
                execution,
                status=ExecutionStatus.FAILED
                if retry_at is None
                else ExecutionStatus.SUBMIT_FAILED,
                retry_count=execution.retry_count + 1,
                next_retry_at=retry_at,
                error=error,
            )
            self._changed.notify_all()

    def record_completion(self, result_id: str, *, succeeded: bool, at: Instant) -> bool:
        with self._changed:
            for key, execution in self._executions.items():
                if (
                    execution.backend_result_id == result_id
                    and execution.status is ExecutionStatus.DISPATCHED
                ):
                    self._executions[key] = replace(
                        execution, status=_finished(succeeded=succeeded), completed_at=at
                    )
                    return True
            return False

    def next_wakeup(self) -> Instant | None:
        with self._changed:
            candidates = [
                schedule.next_run_at
                for schedule in self._schedules.values()
                if schedule.definition.enabled
            ]
            candidates += [
                execution.next_retry_at
                for execution in self._executions.values()
                if execution.status is ExecutionStatus.SUBMIT_FAILED
                and execution.next_retry_at is not None
            ]
            return min(candidates, default=None)

    def recent_executions(self, schedule_id: ScheduleId | None, limit: int) -> Sequence[Execution]:
        with self._changed:
            selected = [
                execution
                for execution in self._executions.values()
                if schedule_id is None or execution.schedule_id == schedule_id
            ]
            selected.sort(key=lambda execution: execution.scheduled_at, reverse=True)
            return selected[:limit]

    def wait_for_change(self, timeout: timedelta) -> bool:
        with self._changed:
            return self._changed.wait(timeout.total_seconds())

    # Internals (callers hold the lock)

    def _holds(self, lease: Lease) -> bool:
        row = self._lease
        return (
            row.holder == lease.holder
            and row.token == lease.token
            and row.expires_at is not None
            and row.expires_at > self._clock.now()
        )

    def _ensure_fence(self, lease: Lease) -> None:
        if not self._holds(lease):
            raise LeaseLostError(f"{lease.holder.value} no longer holds token {lease.token.value}")

    def _insert(
        self, definition: ScheduleDefinition, source: ScheduleSource, now: Instant
    ) -> Schedule:
        schedule = Schedule(
            id=new_schedule_id(),
            definition=definition,
            source=source,
            next_run_at=definition.trigger.next_after(now),
        )
        self._schedules[definition.name] = schedule
        return schedule

    def _update(self, existing: Schedule, definition: ScheduleDefinition, now: Instant) -> Schedule:
        next_run_at = existing.next_run_at
        if definition.trigger != existing.definition.trigger:
            next_run_at = definition.trigger.next_after(now)
        updated = replace(existing, definition=definition, next_run_at=next_run_at)
        self._schedules[definition.name] = updated
        return updated

    def _set_enabled(self, schedule: Schedule, *, enabled: bool, now: Instant) -> None:
        if schedule.definition.enabled == enabled:
            return
        next_run_at = (
            schedule.definition.trigger.next_after(now) if enabled else schedule.next_run_at
        )
        self._schedules[schedule.name] = replace(
            schedule,
            definition=replace(schedule.definition, enabled=enabled),
            next_run_at=next_run_at,
        )


def _finished(*, succeeded: bool) -> ExecutionStatus:
    return ExecutionStatus.COMPLETED if succeeded else ExecutionStatus.TASK_FAILED


def _is_pending(execution: Execution, now: Instant, stale_before: Instant) -> bool:
    if execution.status is ExecutionStatus.REQUESTED:
        return True
    if execution.status is ExecutionStatus.CLAIMED:
        return execution.claimed_at <= stale_before
    if execution.status is ExecutionStatus.SUBMIT_FAILED:
        return execution.next_retry_at is not None and execution.next_retry_at <= now
    return False
