"""The production store: every coordination statement of Goatbeat lives here, once."""

import json
import logging
import time
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Final, LiteralString

from goatbeat.core.errors import ConfigurationError, LeaseLostError, StoreUnavailableError
from goatbeat.core.execution import (
    EARLY_COMPLETION_RETENTION,
    Execution,
    ExecutionStatus,
    Lease,
    SubmissionReceipt,
    idempotency_key_for,
)
from goatbeat.core.ids import (
    FencingToken,
    IdempotencyKey,
    ScheduleId,
    SchedulerId,
    new_schedule_id,
)
from goatbeat.core.misfire import OccurrencePlan
from goatbeat.core.observability import LOGGER_NAME, Event, log_event
from goatbeat.core.schedule import Schedule, ScheduleDefinition, ScheduleSource
from goatbeat.core.serialization import (
    DefinitionColumns,
    definition_from_columns,
    definition_to_columns,
)
from goatbeat.core.submission import PendingSubmission
from goatbeat.core.time import Clock, Instant
from goatbeat.postgres.notify import CHANNEL, Notifier
from goatbeat.postgres.provider import ConnectionProvider, Cursor

_PARTITION: Final = 0
_MICROSECOND: Final = timedelta(microseconds=1)
# NULL means "use the database clock"; only tests pass an explicit instant.
_NOW: Final = "COALESCE(%s::timestamptz, now())"

_SCHEDULE_COLUMNS: Final = (
    "id, name, source, task_path, task_args::text, task_kwargs::text, trigger_kind, "
    "interval_us, start_at, cron, timezone, misfire_policy, misfire_grace_us, max_catch_up, "
    "queue, priority, backend, enabled, next_run_at"
)
_SCHEDULE_FIELD_COUNT: Final = 19
_EXECUTION_COLUMNS: Final = (
    "schedule_id, scheduled_at, idempotency_key, status, scheduler_id, fencing_token, "
    "claimed_at, missed_count, retry_count, dispatched_at, completed_at, next_retry_at, "
    "backend_result_id, error"
)
_SELECT_SCHEDULE: Final = "SELECT " + _SCHEDULE_COLUMNS + " FROM goatbeat_schedule "
DUE_SCHEDULES_QUERY: Final = (
    _SELECT_SCHEDULE + "WHERE enabled AND next_run_at <= %s ORDER BY next_run_at LIMIT %s"
)
_SELECT_EXECUTION: Final = "SELECT " + _EXECUTION_COLUMNS + " FROM goatbeat_execution "
_INSERT_SCHEDULE: Final = (
    "INSERT INTO goatbeat_schedule (id, name, source, task_path, task_args, task_kwargs, "
    "trigger_kind, interval_us, start_at, cron, timezone, misfire_policy, misfire_grace_us, "
    "max_catch_up, queue, priority, backend, enabled, next_run_at) VALUES "
    "(%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
_UPDATE_SCHEDULE: Final = (
    "UPDATE goatbeat_schedule SET name = %s, source = %s, task_path = %s, "
    "task_args = %s::jsonb, task_kwargs = %s::jsonb, trigger_kind = %s, interval_us = %s, "
    "start_at = %s, cron = %s, timezone = %s, misfire_policy = %s, misfire_grace_us = %s, "
    "max_catch_up = %s, queue = %s, priority = %s, backend = %s, enabled = %s, "
    "next_run_at = %s, updated_at = now() WHERE id = %s"
)
_INSERT_EXECUTION: Final = (
    "INSERT INTO goatbeat_execution (" + _EXECUTION_COLUMNS + ") VALUES "
    "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
    "ON CONFLICT (idempotency_key) DO NOTHING"
)
DEFAULT_LOCK_TIMEOUT: Final = timedelta(seconds=1)
DEFAULT_FENCE_IDLE_TIMEOUT: Final = timedelta(seconds=10)
# set_config(..., true) is SET LOCAL with bindable values: it ends with the transaction.
_SET_LOCK_TIMEOUT: Final = "SELECT set_config('lock_timeout', %s, true)"
_SET_IDLE_TIMEOUT: Final = "SELECT set_config('idle_in_transaction_session_timeout', %s, true)"
# Row locks cannot guard names that do not exist yet: concurrent first starts would both insert.
_LOCK_SCHEDULE_WRITES: Final = "SELECT pg_advisory_xact_lock(hashtext('goatbeat.schedules'))"
# A completion and the dispatch record of the same task result must not interleave.
_LOCK_RESULT: Final = "SELECT pg_advisory_xact_lock(hashtext(%s))"
_NOTIFY: Final = "SELECT pg_notify('" + CHANNEL + "', '')"


class PostgresStore:
    """Implements ScheduleStore and LeaseManager. Lease time is PostgreSQL's ``now()``."""

    def __init__(
        self,
        provider: ConnectionProvider,
        *,
        notifier: Notifier | None = None,
        lease_clock: Clock | None = None,
        lock_timeout: timedelta = DEFAULT_LOCK_TIMEOUT,
        fence_idle_timeout: timedelta = DEFAULT_FENCE_IDLE_TIMEOUT,
        logger: logging.Logger | None = None,
    ) -> None:
        if lock_timeout <= timedelta(0) or fence_idle_timeout <= timedelta(0):
            raise ConfigurationError("lock_timeout and fence_idle_timeout must be positive")
        self._provider = provider
        self._lock_timeout = _milliseconds(lock_timeout)
        self._fence_idle_timeout = _milliseconds(fence_idle_timeout)
        self._notifier = notifier
        self._lease_clock = lease_clock
        self._logger = logger or logging.getLogger(LOGGER_NAME)

    def _now(self) -> datetime | None:
        return None if self._lease_clock is None else self._lease_clock.now().datetime

    # LeaseManager

    def acquire(self, holder: SchedulerId, ttl: timedelta) -> Lease | None:
        now = self._now()
        with self._provider.transaction() as cursor:
            # A frozen leader holding the fence must not stall every standby indefinitely.
            cursor.execute(_SET_LOCK_TIMEOUT, [self._lock_timeout])
            cursor.execute(
                "UPDATE goatbeat_lease SET "
                "fencing_token = fencing_token + (holder_id IS DISTINCT FROM %s)::int, "
                "holder_id = %s, expires_at = " + _NOW + " + %s "
                "WHERE partition = %s AND (expires_at <= " + _NOW + " OR holder_id = %s) "
                "RETURNING fencing_token",
                [holder.value, holder.value, now, ttl, _PARTITION, now, holder.value],
            )
            row = cursor.fetchone()
        return None if row is None else Lease(holder, FencingToken(_integer(row[0])))

    def release(self, lease: Lease) -> None:
        with self._provider.transaction() as cursor:
            cursor.execute(_SET_LOCK_TIMEOUT, [self._lock_timeout])
            cursor.execute(
                "UPDATE goatbeat_lease SET expires_at = " + _NOW + " "
                "WHERE partition = %s AND holder_id = %s AND fencing_token = %s",
                [self._now(), _PARTITION, lease.holder.value, lease.token.value],
            )

    # ScheduleStore

    def sync_code_schedules(
        self, definitions: Sequence[ScheduleDefinition], now: Instant, *, prune: bool = False
    ) -> None:
        with self._provider.transaction() as cursor:
            cursor.execute(_LOCK_SCHEDULE_WRITES)
            for definition in sorted(definitions, key=lambda item: item.name):
                existing = self._schedule_by_name(cursor, definition.name, lock=True)
                if existing is None:
                    self._insert(cursor, definition, ScheduleSource.CODE, now)
                else:
                    kept = replace(definition, enabled=existing.definition.enabled)
                    self._update(cursor, existing, kept, now)
            if prune:
                cursor.execute(
                    "UPDATE goatbeat_schedule SET enabled = false, updated_at = now() "
                    "WHERE source = %s AND enabled AND NOT (name = ANY(%s::text[]))",
                    [ScheduleSource.CODE.value, [d.name for d in definitions]],
                )
            cursor.execute(_NOTIFY)

    def save_schedule(self, definition: ScheduleDefinition, now: Instant) -> Schedule:
        with self._provider.transaction() as cursor:
            cursor.execute(_LOCK_SCHEDULE_WRITES)
            existing = self._schedule_by_name(cursor, definition.name, lock=True)
            if existing is not None and existing.source is ScheduleSource.CODE:
                raise ConfigurationError(f"schedule {definition.name!r} is declared in code")
            if existing is None:
                saved = self._insert(cursor, definition, ScheduleSource.STORE, now)
            else:
                saved = self._update(cursor, existing, definition, now)
            cursor.execute(_NOTIFY)
        return saved

    def get_schedule(self, name: str) -> Schedule | None:
        with self._provider.transaction() as cursor:
            return self._schedule_by_name(cursor, name, lock=False)

    def list_schedules(self) -> Sequence[Schedule]:
        with self._provider.transaction() as cursor:
            cursor.execute(_SELECT_SCHEDULE + "ORDER BY name")
            return self._decodable(cursor.fetchall())

    def set_enabled(self, name: str, *, enabled: bool, now: Instant) -> None:
        with self._provider.transaction() as cursor:
            schedule = self._schedule_by_name(cursor, name, lock=True)
            if schedule is None:
                raise ConfigurationError(f"unknown schedule {name!r}")
            if schedule.definition.enabled == enabled:
                return
            next_run_at = schedule.next_run_at
            if enabled:
                next_run_at = schedule.definition.trigger.next_after(now)
            cursor.execute(
                "UPDATE goatbeat_schedule SET enabled = %s, next_run_at = %s, "
                "updated_at = now() WHERE id = %s",
                [enabled, next_run_at.datetime, schedule.id.value],
            )
            cursor.execute(_NOTIFY)

    def due_schedules(self, now: Instant, limit: int) -> Sequence[Schedule]:
        with self._provider.transaction() as cursor:
            cursor.execute(DUE_SCHEDULES_QUERY, [now.datetime, limit])
            return self._decodable(cursor.fetchall())

    def claim(
        self, lease: Lease, schedule: Schedule, plan: OccurrencePlan, now: Instant
    ) -> Sequence[Execution]:
        with self._provider.transaction() as cursor:
            return self.claim_in(cursor, lease, schedule, plan, now)

    def claim_in(
        self, cursor: Cursor, lease: Lease, schedule: Schedule, plan: OccurrencePlan, now: Instant
    ) -> Sequence[Execution]:
        """Claim inside a transaction the caller owns (Django's ``atomic`` for instance)."""
        self._ensure_fence(cursor, lease)
        self._lock_schedule(cursor, schedule)
        created: list[Execution] = []
        for claim in plan.claims:
            execution = Execution(
                schedule_id=schedule.id,
                scheduled_at=claim.scheduled_at,
                idempotency_key=idempotency_key_for(schedule.id, claim.scheduled_at),
                status=claim.status,
                scheduler_id=lease.holder,
                fencing_token=lease.token,
                claimed_at=now,
                missed_count=claim.missed_count,
            )
            cursor.execute(_INSERT_EXECUTION, _execution_values(execution))
            if cursor.rowcount == 1:
                created.append(execution)
        cursor.execute(
            "UPDATE goatbeat_schedule SET next_run_at = %s WHERE id = %s AND next_run_at = %s",
            [plan.next_run_at.datetime, schedule.id.value, schedule.next_run_at.datetime],
        )
        return created

    def request_run(
        self, schedule: Schedule, key: IdempotencyKey, requested_by: SchedulerId, now: Instant
    ) -> Execution:
        execution = Execution(
            schedule_id=schedule.id,
            scheduled_at=now,
            idempotency_key=key,
            status=ExecutionStatus.REQUESTED,
            scheduler_id=requested_by,
            fencing_token=FencingToken(0),
            claimed_at=now,
        )
        with self._provider.transaction() as cursor:
            self._lock_schedule(cursor, schedule)
            cursor.execute(_INSERT_EXECUTION, _execution_values(execution))
            cursor.execute(_SELECT_EXECUTION + "WHERE idempotency_key = %s", [key.value])
            row = cursor.fetchone()
            cursor.execute(_NOTIFY)
        if row is None:
            raise StoreUnavailableError(f"requested run {key.value} was not recorded")
        return _execution(row)

    def pending_submissions(
        self, now: Instant, stale_before: Instant, limit: int
    ) -> Sequence[PendingSubmission]:
        with self._provider.transaction() as cursor:
            cursor.execute(
                "SELECT e.schedule_id, e.scheduled_at, e.idempotency_key, e.status, "
                "e.scheduler_id, e.fencing_token, e.claimed_at, e.missed_count, e.retry_count, "
                "e.dispatched_at, e.completed_at, e.next_retry_at, e.backend_result_id, e.error, "
                "s.id, s.name, s.source, s.task_path, s.task_args::text, s.task_kwargs::text, "
                "s.trigger_kind, s.interval_us, s.start_at, s.cron, s.timezone, "
                "s.misfire_policy, s.misfire_grace_us, s.max_catch_up, s.queue, s.priority, "
                "s.backend, s.enabled, s.next_run_at "
                "FROM goatbeat_execution e JOIN goatbeat_schedule s ON s.id = e.schedule_id "
                "WHERE e.status = %s OR (e.status = %s AND e.claimed_at <= %s) "
                "OR (e.status = %s AND e.next_retry_at <= %s) "
                "ORDER BY e.scheduled_at LIMIT %s",
                [
                    ExecutionStatus.REQUESTED.value,
                    ExecutionStatus.CLAIMED.value,
                    stale_before.datetime,
                    ExecutionStatus.SUBMIT_FAILED.value,
                    now.datetime,
                    limit,
                ],
            )
            rows = cursor.fetchall()
        pending: list[PendingSubmission] = []
        split = len(_EXECUTION_COLUMNS.split(","))
        for row in rows:
            schedule = self._decode(row[split:])
            if schedule is not None:
                pending.append(PendingSubmission(_execution(row[:split]), schedule))
        return pending

    def mark_dispatched(self, key: IdempotencyKey, at: Instant, receipt: SubmissionReceipt) -> None:
        status, completed_at = receipt.status, None if receipt.outcome is None else at.datetime
        with self._provider.transaction() as cursor:
            if receipt.result_id is not None:
                cursor.execute(_LOCK_RESULT, [receipt.result_id])
                cursor.execute(
                    "DELETE FROM goatbeat_early_completion WHERE result_id = %s "
                    "RETURNING status, completed_at",
                    [receipt.result_id],
                )
                early = cursor.fetchone()
                if early is not None:
                    status, completed_at = (
                        ExecutionStatus(_text(early[0])),
                        _instant(early[1]).datetime,
                    )
            cursor.execute(
                "UPDATE goatbeat_execution SET status = %s, dispatched_at = %s, "
                "completed_at = %s, backend_result_id = %s, next_retry_at = NULL, error = NULL "
                "WHERE idempotency_key = %s AND status NOT IN ('completed', 'task_failed')",
                [status.value, at.datetime, completed_at, receipt.result_id, key.value],
            )

    def mark_submit_failed(self, key: IdempotencyKey, error: str, retry_at: Instant | None) -> None:
        status = ExecutionStatus.FAILED if retry_at is None else ExecutionStatus.SUBMIT_FAILED
        with self._provider.transaction() as cursor:
            cursor.execute(
                "UPDATE goatbeat_execution SET status = %s, retry_count = retry_count + 1, "
                "next_retry_at = %s, error = %s WHERE idempotency_key = %s",
                [status.value, None if retry_at is None else retry_at.datetime, error, key.value],
            )

    def record_completion(
        self, result_id: str, task_path: str, *, succeeded: bool, at: Instant
    ) -> bool:
        status = ExecutionStatus.COMPLETED if succeeded else ExecutionStatus.TASK_FAILED
        with self._provider.transaction() as cursor:
            cursor.execute(_LOCK_RESULT, [result_id])
            cursor.execute(
                "UPDATE goatbeat_execution SET status = %s, completed_at = %s "
                "WHERE backend_result_id = %s AND status = %s",
                [status.value, at.datetime, result_id, ExecutionStatus.DISPATCHED.value],
            )
            if cursor.rowcount > 0:
                return True
            cursor.execute(
                "DELETE FROM goatbeat_early_completion WHERE completed_at < %s",
                [(at - EARLY_COMPLETION_RETENTION).datetime],
            )
            cursor.execute(
                "INSERT INTO goatbeat_early_completion (result_id, status, completed_at) "
                "SELECT %s, %s, %s WHERE EXISTS "
                "(SELECT 1 FROM goatbeat_schedule WHERE task_path = %s) ON CONFLICT DO NOTHING",
                [result_id, status.value, at.datetime, task_path],
            )
            return False

    def next_wakeup(self) -> Instant | None:
        with self._provider.transaction() as cursor:
            cursor.execute(
                "SELECT LEAST("
                "(SELECT MIN(next_run_at) FROM goatbeat_schedule WHERE enabled), "
                "(SELECT MIN(next_retry_at) FROM goatbeat_execution WHERE status = %s))",
                [ExecutionStatus.SUBMIT_FAILED.value],
            )
            row = cursor.fetchone()
        return None if row is None else _optional_instant(row[0])

    def recent_executions(self, schedule_id: ScheduleId | None, limit: int) -> Sequence[Execution]:
        with self._provider.transaction() as cursor:
            if schedule_id is None:
                cursor.execute(_SELECT_EXECUTION + "ORDER BY scheduled_at DESC LIMIT %s", [limit])
            else:
                cursor.execute(
                    _SELECT_EXECUTION + "WHERE schedule_id = %s ORDER BY scheduled_at DESC "
                    "LIMIT %s",
                    [schedule_id.value, limit],
                )
            return [_execution(row) for row in cursor.fetchall()]

    def wait_for_change(self, timeout: timedelta) -> bool:
        if self._notifier is None:
            time.sleep(timeout.total_seconds())
            return False
        return self._notifier.wait(timeout)

    # Internals

    def _ensure_fence(self, cursor: Cursor, lease: Lease) -> None:
        """FOR SHARE makes a concurrent takeover wait until this claim transaction ends.

        The idle timeout lets PostgreSQL end that transaction if the leader freezes.
        """
        cursor.execute(_SET_IDLE_TIMEOUT, [self._fence_idle_timeout])
        cursor.execute(
            "SELECT 1 FROM goatbeat_lease WHERE partition = %s AND holder_id = %s "
            "AND fencing_token = %s AND expires_at > " + _NOW + " FOR SHARE",
            [_PARTITION, lease.holder.value, lease.token.value, self._now()],
        )
        if cursor.fetchone() is None:
            raise LeaseLostError(f"{lease.holder.value} no longer holds token {lease.token.value}")

    def _lock_schedule(self, cursor: Cursor, schedule: Schedule) -> None:
        """KEY SHARE keeps the schedule from being deleted before the executions commit."""
        cursor.execute(
            "SELECT 1 FROM goatbeat_schedule WHERE id = %s FOR KEY SHARE", [schedule.id.value]
        )
        if cursor.fetchone() is None:
            raise ConfigurationError(f"schedule {schedule.name!r} no longer exists")

    def _schedule_by_name(self, cursor: Cursor, name: str, *, lock: bool) -> Schedule | None:
        query: LiteralString = _SELECT_SCHEDULE + "WHERE name = %s"
        cursor.execute(query + " FOR UPDATE" if lock else query, [name])
        row = cursor.fetchone()
        return None if row is None else _schedule(row)

    def _decode(self, row: Sequence[object]) -> Schedule | None:
        try:
            return _schedule(row)
        except (ConfigurationError, ValueError) as error:
            log_event(
                self._logger,
                Event.SCHEDULE_INVALID,
                logging.ERROR,
                schedule=str(row[1]),
                error=str(error),
            )
            return None

    def _decodable(self, rows: Sequence[Sequence[object]]) -> list[Schedule]:
        """Skip rows this version cannot decode, so one bad row never blocks the others."""
        return [schedule for row in rows if (schedule := self._decode(row)) is not None]

    def _insert(
        self, cursor: Cursor, definition: ScheduleDefinition, source: ScheduleSource, now: Instant
    ) -> Schedule:
        schedule = Schedule(
            id=new_schedule_id(),
            definition=definition,
            source=source,
            next_run_at=definition.trigger.next_after(now),
        )
        cursor.execute(_INSERT_SCHEDULE, _schedule_values(schedule))
        return schedule

    def _update(
        self, cursor: Cursor, existing: Schedule, definition: ScheduleDefinition, now: Instant
    ) -> Schedule:
        next_run_at = existing.next_run_at
        if definition.trigger != existing.definition.trigger:
            next_run_at = definition.trigger.next_after(now)
        updated = Schedule(existing.id, definition, existing.source, next_run_at)
        values = _schedule_values(updated)
        cursor.execute(_UPDATE_SCHEDULE, [*values[1:], values[0]])
        return updated


def _schedule_values(schedule: Schedule) -> list[object]:
    columns = definition_to_columns(schedule.definition)
    interval = columns["interval"]
    start_at = columns["start_at"]
    return [
        schedule.id.value,
        columns["name"],
        schedule.source.value,
        columns["task_path"],
        columns["task_args"],
        columns["task_kwargs"],
        columns["trigger_kind"],
        None if interval is None else interval // _MICROSECOND,
        None if start_at is None else start_at.datetime,
        columns["cron"],
        columns["timezone"],
        columns["misfire_policy"],
        columns["misfire_grace"] // _MICROSECOND,
        columns["max_catch_up"],
        columns["queue"],
        columns["priority"],
        columns["backend"],
        columns["enabled"],
        schedule.next_run_at.datetime,
    ]


def _schedule(row: Sequence[object]) -> Schedule:
    if len(row) != _SCHEDULE_FIELD_COUNT:
        raise ValueError(f"expected {_SCHEDULE_FIELD_COUNT} schedule columns, got {len(row)}")
    interval_us = _optional_integer(row[7])
    columns = DefinitionColumns(
        name=_text(row[1]),
        task_path=_text(row[3]),
        task_args=_json_text(row[4]),
        task_kwargs=_json_text(row[5]),
        trigger_kind=_text(row[6]),
        interval=None if interval_us is None else interval_us * _MICROSECOND,
        start_at=_optional_instant(row[8]),
        cron=_optional_text(row[9]),
        timezone=_optional_text(row[10]),
        misfire_policy=_text(row[11]),
        misfire_grace=_integer(row[12]) * _MICROSECOND,
        max_catch_up=_integer(row[13]),
        queue=_optional_text(row[14]),
        priority=_optional_integer(row[15]),
        backend=_optional_text(row[16]),
        enabled=bool(row[17]),
    )
    return Schedule(
        id=ScheduleId(_text(row[0])),
        definition=definition_from_columns(columns),
        source=ScheduleSource(_text(row[2])),
        next_run_at=_instant(row[18]),
    )


def _execution_values(execution: Execution) -> list[object]:
    return [
        execution.schedule_id.value,
        execution.scheduled_at.datetime,
        execution.idempotency_key.value,
        execution.status.value,
        execution.scheduler_id.value,
        execution.fencing_token.value,
        execution.claimed_at.datetime,
        execution.missed_count,
        execution.retry_count,
        _optional_datetime(execution.dispatched_at),
        _optional_datetime(execution.completed_at),
        _optional_datetime(execution.next_retry_at),
        execution.backend_result_id,
        execution.error,
    ]


def _execution(row: Sequence[object]) -> Execution:
    return Execution(
        schedule_id=ScheduleId(_text(row[0])),
        scheduled_at=_instant(row[1]),
        idempotency_key=IdempotencyKey(_text(row[2])),
        status=ExecutionStatus(_text(row[3])),
        scheduler_id=SchedulerId(_text(row[4])),
        fencing_token=FencingToken(_integer(row[5])),
        claimed_at=_instant(row[6]),
        missed_count=_integer(row[7]),
        retry_count=_integer(row[8]),
        dispatched_at=_optional_instant(row[9]),
        completed_at=_optional_instant(row[10]),
        next_retry_at=_optional_instant(row[11]),
        backend_result_id=_optional_text(row[12]),
        error=_optional_text(row[13]),
    )


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(f"expected text, got {value!r}")
    return value


def _optional_text(value: object) -> str | None:
    return None if value is None else _text(value)


def _json_text(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value)


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"expected an integer, got {value!r}")
    return value


def _optional_integer(value: object) -> int | None:
    return None if value is None else _integer(value)


def _instant(value: object) -> Instant:
    if not isinstance(value, datetime):
        raise ValueError(f"expected a timestamp, got {value!r}")
    return Instant.of(value)


def _optional_instant(value: object) -> Instant | None:
    return None if value is None else _instant(value)


def _optional_datetime(value: Instant | None) -> datetime | None:
    return None if value is None else value.datetime


def _milliseconds(value: timedelta) -> str:
    return f"{max(1, round(value.total_seconds() * 1000))}ms"
