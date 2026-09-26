"""SQLite store for development and single-host setups.

Lease expiry uses the injected clock, so SQLite is not a multi-host coordination backend.
"""

import logging
import sqlite3
import threading
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Final

from goatbeat.core.errors import ConfigurationError, LeaseLostError
from goatbeat.core.execution import (
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

_BUSY_TIMEOUT_MS: Final = 5_000
_PARTITION: Final = 0
_MICROSECOND: Final = timedelta(microseconds=1)

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS goatbeat_schedule (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    task_path TEXT NOT NULL,
    task_args TEXT NOT NULL,
    task_kwargs TEXT NOT NULL,
    trigger_kind TEXT NOT NULL,
    interval_us INTEGER,
    start_at_us INTEGER,
    cron TEXT,
    timezone TEXT,
    misfire_policy TEXT NOT NULL,
    misfire_grace_us INTEGER NOT NULL,
    max_catch_up INTEGER NOT NULL,
    queue TEXT,
    priority INTEGER,
    backend TEXT,
    enabled INTEGER NOT NULL,
    next_run_at_us INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS goatbeat_schedule_due
    ON goatbeat_schedule (next_run_at_us) WHERE enabled = 1;
CREATE TABLE IF NOT EXISTS goatbeat_execution (
    id INTEGER PRIMARY KEY,
    schedule_id TEXT NOT NULL REFERENCES goatbeat_schedule (id) ON DELETE CASCADE,
    scheduled_at_us INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    scheduler_id TEXT NOT NULL,
    fencing_token INTEGER NOT NULL,
    claimed_at_us INTEGER NOT NULL,
    missed_count INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    dispatched_at_us INTEGER,
    completed_at_us INTEGER,
    next_retry_at_us INTEGER,
    backend_result_id TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS goatbeat_execution_history
    ON goatbeat_execution (schedule_id, scheduled_at_us);
CREATE INDEX IF NOT EXISTS goatbeat_execution_result
    ON goatbeat_execution (backend_result_id) WHERE backend_result_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS goatbeat_execution_pending
    ON goatbeat_execution (status, next_retry_at_us, claimed_at_us);
CREATE TABLE IF NOT EXISTS goatbeat_lease (
    partition INTEGER PRIMARY KEY,
    holder_id TEXT,
    fencing_token INTEGER NOT NULL,
    expires_at_us INTEGER NOT NULL
);
INSERT OR IGNORE INTO goatbeat_lease (partition, holder_id, fencing_token, expires_at_us)
    VALUES (0, NULL, 0, 0);
"""

_SCHEDULE_COLUMNS: Final = (
    "id, name, source, task_path, task_args, task_kwargs, trigger_kind, interval_us, "
    "start_at_us, cron, timezone, misfire_policy, misfire_grace_us, max_catch_up, queue, "
    "priority, backend, enabled, next_run_at_us"
)
_EXECUTION_COLUMNS: Final = (
    "schedule_id, scheduled_at_us, idempotency_key, status, scheduler_id, fencing_token, "
    "claimed_at_us, missed_count, retry_count, dispatched_at_us, completed_at_us, "
    "next_retry_at_us, backend_result_id, error"
)

type _Row = sqlite3.Row


class SQLiteStore:
    """Implements ScheduleStore and LeaseManager on one SQLite file."""

    def __init__(
        self, path: Path | str, clock: Clock, logger: logging.Logger | None = None
    ) -> None:
        self._clock = clock
        self._logger = logger or logging.getLogger(LOGGER_NAME)
        self._lock = threading.Lock()
        self._changed = threading.Condition()
        self._connection = sqlite3.connect(
            path, isolation_level=None, check_same_thread=False, timeout=_BUSY_TIMEOUT_MS / 1000
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA foreign_keys = ON")
        with self._lock:
            self._connection.executescript(_SCHEMA)

    def close(self) -> None:
        self._connection.close()

    @contextmanager
    def _write(self) -> Generator[sqlite3.Cursor]:
        """BEGIN IMMEDIATE takes the write lock up front, serializing claims across processes."""
        with self._lock:
            cursor = self._connection.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            try:
                yield cursor
            except BaseException:
                cursor.execute("ROLLBACK")
                raise
            cursor.execute("COMMIT")

    def _read(self, sql: str, parameters: Sequence[object] = ()) -> list[_Row]:
        with self._lock:
            return self._connection.execute(sql, parameters).fetchall()

    def _notify(self) -> None:
        with self._changed:
            self._changed.notify_all()

    # LeaseManager

    def acquire(self, holder: SchedulerId, ttl: timedelta) -> Lease | None:
        now = self._clock.now().timestamp_us
        with self._write() as cursor:
            row = cursor.execute(
                "UPDATE goatbeat_lease SET "
                "fencing_token = fencing_token + (holder_id IS NOT ?), "
                "holder_id = ?, expires_at_us = ? "
                "WHERE partition = ? AND (expires_at_us <= ? OR holder_id = ?) "
                "RETURNING fencing_token",
                (
                    holder.value,
                    holder.value,
                    now + ttl // _MICROSECOND,
                    _PARTITION,
                    now,
                    holder.value,
                ),
            ).fetchone()
        return None if row is None else Lease(holder, FencingToken(row[0]))

    def release(self, lease: Lease) -> None:
        with self._write() as cursor:
            cursor.execute(
                "UPDATE goatbeat_lease SET expires_at_us = ? "
                "WHERE partition = ? AND holder_id = ? AND fencing_token = ?",
                (self._clock.now().timestamp_us, _PARTITION, lease.holder.value, lease.token.value),
            )

    # ScheduleStore

    def sync_code_schedules(
        self, definitions: Sequence[ScheduleDefinition], now: Instant, *, prune: bool = False
    ) -> None:
        with self._write() as cursor:
            for definition in definitions:
                existing = self._schedule_by_name(cursor, definition.name)
                if existing is None:
                    self._insert(cursor, definition, ScheduleSource.CODE, now)
                else:
                    self._update(cursor, existing, definition, now, keep_enabled=True)
            if prune:
                listed = {definition.name for definition in definitions}
                rows = cursor.execute(
                    "SELECT name FROM goatbeat_schedule WHERE source = ? AND enabled = 1",
                    (ScheduleSource.CODE.value,),
                ).fetchall()
                for (name,) in rows:
                    if name not in listed:
                        cursor.execute(
                            "UPDATE goatbeat_schedule SET enabled = 0 WHERE name = ?", (name,)
                        )
        self._notify()

    def save_schedule(self, definition: ScheduleDefinition, now: Instant) -> Schedule:
        with self._write() as cursor:
            existing = self._schedule_by_name(cursor, definition.name)
            if existing is not None and existing.source is ScheduleSource.CODE:
                raise ConfigurationError(f"schedule {definition.name!r} is declared in code")
            if existing is None:
                saved = self._insert(cursor, definition, ScheduleSource.STORE, now)
            else:
                saved = self._update(cursor, existing, definition, now, keep_enabled=False)
        self._notify()
        return saved

    def get_schedule(self, name: str) -> Schedule | None:
        rows = self._read(
            f"SELECT {_SCHEDULE_COLUMNS} FROM goatbeat_schedule WHERE name = ?", (name,)
        )
        return _schedule(rows[0]) if rows else None

    def list_schedules(self) -> Sequence[Schedule]:
        rows = self._read(f"SELECT {_SCHEDULE_COLUMNS} FROM goatbeat_schedule ORDER BY name")
        return self._decodable(rows)

    def set_enabled(self, name: str, *, enabled: bool, now: Instant) -> None:
        with self._write() as cursor:
            schedule = self._schedule_by_name(cursor, name)
            if schedule is None:
                raise ConfigurationError(f"unknown schedule {name!r}")
            if schedule.definition.enabled != enabled:
                next_run_at = schedule.next_run_at
                if enabled:
                    next_run_at = schedule.definition.trigger.next_after(now)
                cursor.execute(
                    "UPDATE goatbeat_schedule SET enabled = ?, next_run_at_us = ? WHERE id = ?",
                    (int(enabled), next_run_at.timestamp_us, schedule.id.value),
                )
        self._notify()

    def due_schedules(self, now: Instant, limit: int) -> Sequence[Schedule]:
        rows = self._read(
            f"SELECT {_SCHEDULE_COLUMNS} FROM goatbeat_schedule "
            "WHERE enabled = 1 AND next_run_at_us <= ? ORDER BY next_run_at_us LIMIT ?",
            (now.timestamp_us, limit),
        )
        return self._decodable(rows)

    def claim(
        self, lease: Lease, schedule: Schedule, plan: OccurrencePlan, now: Instant
    ) -> Sequence[Execution]:
        created: list[Execution] = []
        with self._write() as cursor:
            self._ensure_fence(cursor, lease)
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
                if self._insert_execution(cursor, execution):
                    created.append(execution)
            cursor.execute(
                "UPDATE goatbeat_schedule SET next_run_at_us = ? "
                "WHERE id = ? AND next_run_at_us = ?",
                (
                    plan.next_run_at.timestamp_us,
                    schedule.id.value,
                    schedule.next_run_at.timestamp_us,
                ),
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
        with self._write() as cursor:
            self._insert_execution(cursor, execution)
            row = cursor.execute(
                f"SELECT {_EXECUTION_COLUMNS} FROM goatbeat_execution WHERE idempotency_key = ?",
                (key.value,),
            ).fetchone()
        self._notify()
        return _execution(row)

    def pending_submissions(
        self, now: Instant, stale_before: Instant, limit: int
    ) -> Sequence[PendingSubmission]:
        execution_columns = ", ".join(f"e.{c.strip()}" for c in _EXECUTION_COLUMNS.split(","))
        schedule_columns = ", ".join(f"s.{c.strip()}" for c in _SCHEDULE_COLUMNS.split(","))
        rows = self._read(
            f"SELECT {execution_columns}, {schedule_columns} FROM goatbeat_execution e "
            "JOIN goatbeat_schedule s ON s.id = e.schedule_id "
            "WHERE e.status = ? OR (e.status = ? AND e.claimed_at_us <= ?) "
            "OR (e.status = ? AND e.next_retry_at_us <= ?) "
            "ORDER BY e.scheduled_at_us LIMIT ?",
            (
                ExecutionStatus.REQUESTED.value,
                ExecutionStatus.CLAIMED.value,
                stale_before.timestamp_us,
                ExecutionStatus.SUBMIT_FAILED.value,
                now.timestamp_us,
                limit,
            ),
        )
        split = len(_EXECUTION_COLUMNS.split(","))
        return [PendingSubmission(_execution(row), _schedule(row, offset=split)) for row in rows]

    def mark_dispatched(self, key: IdempotencyKey, at: Instant, receipt: SubmissionReceipt) -> None:
        with self._write() as cursor:
            cursor.execute(
                "UPDATE goatbeat_execution SET status = ?, dispatched_at_us = ?, "
                "completed_at_us = ?, backend_result_id = ?, next_retry_at_us = NULL, "
                "error = NULL WHERE idempotency_key = ?",
                (
                    receipt.status.value,
                    at.timestamp_us,
                    None if receipt.outcome is None else at.timestamp_us,
                    receipt.result_id,
                    key.value,
                ),
            )

    def mark_submit_failed(self, key: IdempotencyKey, error: str, retry_at: Instant | None) -> None:
        status = ExecutionStatus.FAILED if retry_at is None else ExecutionStatus.SUBMIT_FAILED
        with self._write() as cursor:
            cursor.execute(
                "UPDATE goatbeat_execution SET status = ?, retry_count = retry_count + 1, "
                "next_retry_at_us = ?, error = ? WHERE idempotency_key = ?",
                (
                    status.value,
                    None if retry_at is None else retry_at.timestamp_us,
                    error,
                    key.value,
                ),
            )
        self._notify()

    def record_completion(self, result_id: str, *, succeeded: bool, at: Instant) -> bool:
        status = ExecutionStatus.COMPLETED if succeeded else ExecutionStatus.TASK_FAILED
        with self._write() as cursor:
            cursor.execute(
                "UPDATE goatbeat_execution SET status = ?, completed_at_us = ? "
                "WHERE backend_result_id = ? AND status = ?",
                (status.value, at.timestamp_us, result_id, ExecutionStatus.DISPATCHED.value),
            )
            return cursor.rowcount > 0

    def next_wakeup(self) -> Instant | None:
        rows = self._read(
            "SELECT MIN(value) FROM ("
            "SELECT MIN(next_run_at_us) AS value FROM goatbeat_schedule WHERE enabled = 1 "
            "UNION ALL SELECT MIN(next_retry_at_us) FROM goatbeat_execution WHERE status = ?)",
            (ExecutionStatus.SUBMIT_FAILED.value,),
        )
        value: int | None = rows[0][0]
        return None if value is None else Instant.from_timestamp_us(value)

    def recent_executions(self, schedule_id: ScheduleId | None, limit: int) -> Sequence[Execution]:
        if schedule_id is None:
            rows = self._read(
                f"SELECT {_EXECUTION_COLUMNS} FROM goatbeat_execution "
                "ORDER BY scheduled_at_us DESC LIMIT ?",
                (limit,),
            )
        else:
            rows = self._read(
                f"SELECT {_EXECUTION_COLUMNS} FROM goatbeat_execution WHERE schedule_id = ? "
                "ORDER BY scheduled_at_us DESC LIMIT ?",
                (schedule_id.value, limit),
            )
        return [_execution(row) for row in rows]

    def wait_for_change(self, timeout: timedelta) -> bool:
        """Only changes made through this instance wake it; others arrive on the next poll."""
        with self._changed:
            return self._changed.wait(timeout.total_seconds())

    # Internals

    def _decodable(self, rows: Sequence[_Row]) -> list[Schedule]:
        """Skip rows this version cannot decode, so one bad row never blocks the others."""
        schedules: list[Schedule] = []
        for row in rows:
            try:
                schedules.append(_schedule(row))
            except (ConfigurationError, ValueError) as error:
                log_event(
                    self._logger,
                    Event.SCHEDULE_INVALID,
                    logging.ERROR,
                    schedule=row[1],
                    error=str(error),
                )
        return schedules

    def _ensure_fence(self, cursor: sqlite3.Cursor, lease: Lease) -> None:
        row = cursor.execute(
            "SELECT 1 FROM goatbeat_lease WHERE partition = ? AND holder_id = ? "
            "AND fencing_token = ? AND expires_at_us > ?",
            (_PARTITION, lease.holder.value, lease.token.value, self._clock.now().timestamp_us),
        ).fetchone()
        if row is None:
            raise LeaseLostError(f"{lease.holder.value} no longer holds token {lease.token.value}")

    def _schedule_by_name(self, cursor: sqlite3.Cursor, name: str) -> Schedule | None:
        row = cursor.execute(
            f"SELECT {_SCHEDULE_COLUMNS} FROM goatbeat_schedule WHERE name = ?", (name,)
        ).fetchone()
        return None if row is None else _schedule(row)

    def _insert(
        self,
        cursor: sqlite3.Cursor,
        definition: ScheduleDefinition,
        source: ScheduleSource,
        now: Instant,
    ) -> Schedule:
        schedule = Schedule(
            id=new_schedule_id(),
            definition=definition,
            source=source,
            next_run_at=definition.trigger.next_after(now),
        )
        placeholders = ", ".join("?" for _ in _SCHEDULE_COLUMNS.split(","))
        cursor.execute(
            f"INSERT INTO goatbeat_schedule ({_SCHEDULE_COLUMNS}) VALUES ({placeholders})",
            _schedule_values(schedule),
        )
        return schedule

    def _update(
        self,
        cursor: sqlite3.Cursor,
        existing: Schedule,
        definition: ScheduleDefinition,
        now: Instant,
        *,
        keep_enabled: bool,
    ) -> Schedule:
        if keep_enabled:
            definition = replace(definition, enabled=existing.definition.enabled)
        next_run_at = existing.next_run_at
        if definition.trigger != existing.definition.trigger:
            next_run_at = definition.trigger.next_after(now)
        updated = Schedule(existing.id, definition, existing.source, next_run_at)
        assignments = ", ".join(f"{c.strip()} = ?" for c in _SCHEDULE_COLUMNS.split(",")[1:])
        values = _schedule_values(updated)
        cursor.execute(
            f"UPDATE goatbeat_schedule SET {assignments} WHERE id = ?", (*values[1:], values[0])
        )
        return updated

    def _insert_execution(self, cursor: sqlite3.Cursor, execution: Execution) -> bool:
        placeholders = ", ".join("?" for _ in _EXECUTION_COLUMNS.split(","))
        cursor.execute(
            f"INSERT INTO goatbeat_execution ({_EXECUTION_COLUMNS}) VALUES ({placeholders}) "
            "ON CONFLICT DO NOTHING",
            _execution_values(execution),
        )
        return cursor.rowcount == 1


def _us(value: Instant | None) -> int | None:
    return None if value is None else value.timestamp_us


def _instant(value: int | None) -> Instant | None:
    return None if value is None else Instant.from_timestamp_us(value)


def _schedule_values(schedule: Schedule) -> tuple[object, ...]:
    columns = definition_to_columns(schedule.definition)
    interval = columns["interval"]
    return (
        schedule.id.value,
        columns["name"],
        schedule.source.value,
        columns["task_path"],
        columns["task_args"],
        columns["task_kwargs"],
        columns["trigger_kind"],
        None if interval is None else interval // _MICROSECOND,
        _us(columns["start_at"]),
        columns["cron"],
        columns["timezone"],
        columns["misfire_policy"],
        columns["misfire_grace"] // _MICROSECOND,
        columns["max_catch_up"],
        columns["queue"],
        columns["priority"],
        columns["backend"],
        int(columns["enabled"]),
        schedule.next_run_at.timestamp_us,
    )


def _schedule(row: _Row, offset: int = 0) -> Schedule:
    value = [row[offset + index] for index in range(len(_SCHEDULE_COLUMNS.split(",")))]
    interval_us: int | None = value[7]
    columns = DefinitionColumns(
        name=value[1],
        task_path=value[3],
        task_args=value[4],
        task_kwargs=value[5],
        trigger_kind=value[6],
        interval=None if interval_us is None else interval_us * _MICROSECOND,
        start_at=_instant(value[8]),
        cron=value[9],
        timezone=value[10],
        misfire_policy=value[11],
        misfire_grace=value[12] * _MICROSECOND,
        max_catch_up=value[13],
        queue=value[14],
        priority=value[15],
        backend=value[16],
        enabled=bool(value[17]),
    )
    return Schedule(
        id=ScheduleId(value[0]),
        definition=definition_from_columns(columns),
        source=ScheduleSource(value[2]),
        next_run_at=Instant.from_timestamp_us(value[18]),
    )


def _execution_values(execution: Execution) -> tuple[object, ...]:
    return (
        execution.schedule_id.value,
        execution.scheduled_at.timestamp_us,
        execution.idempotency_key.value,
        execution.status.value,
        execution.scheduler_id.value,
        execution.fencing_token.value,
        execution.claimed_at.timestamp_us,
        execution.missed_count,
        execution.retry_count,
        _us(execution.dispatched_at),
        _us(execution.completed_at),
        _us(execution.next_retry_at),
        execution.backend_result_id,
        execution.error,
    )


def _execution(row: _Row) -> Execution:
    return Execution(
        schedule_id=ScheduleId(row[0]),
        scheduled_at=Instant.from_timestamp_us(row[1]),
        idempotency_key=IdempotencyKey(row[2]),
        status=ExecutionStatus(row[3]),
        scheduler_id=SchedulerId(row[4]),
        fencing_token=FencingToken(row[5]),
        claimed_at=Instant.from_timestamp_us(row[6]),
        missed_count=row[7],
        retry_count=row[8],
        dispatched_at=_instant(row[9]),
        completed_at=_instant(row[10]),
        next_retry_at=_instant(row[11]),
        backend_result_id=row[12],
        error=row[13],
    )
