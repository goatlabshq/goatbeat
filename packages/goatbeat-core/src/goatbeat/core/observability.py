"""Structured logging and metrics hooks; Prometheus and OpenTelemetry plug into MetricsSink."""

import json
import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Protocol, override

from goatbeat.core.execution import ExecutionStatus

LOGGER_NAME: Final = "goatbeat"
EXTRA_KEY: Final = "goatbeat"

type FieldValue = str | int | float | bool | None


class Event(StrEnum):
    SCHEDULER_STARTED = "scheduler.started"
    SCHEDULER_STOPPED = "scheduler.stopped"
    LEASE_ACQUIRED = "lease.acquired"
    LEADER_LOST = "leader.lost"
    FAILOVER = "failover"
    OCCURRENCE_CLAIMED = "occurrence.claimed"
    OCCURRENCE_SKIPPED = "occurrence.skipped"
    OCCURRENCE_DISPATCHED = "occurrence.dispatched"
    SUBMISSION_FAILED = "submission.failed"
    STORE_UNAVAILABLE = "store.unavailable"


def log_event(
    logger: logging.Logger,
    event: Event,
    level: int = logging.INFO,
    *,
    exc_info: bool = False,
    **fields: FieldValue,
) -> None:
    logger.log(
        level, event.value, exc_info=exc_info, extra={EXTRA_KEY: {"event": event.value, **fields}}
    )


class JsonFormatter(logging.Formatter):
    """One JSON object per line, carrying the structured fields of log_event."""

    @override
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        structured: object = record.__dict__.get(EXTRA_KEY)
        if isinstance(structured, dict):
            payload.update(structured)  # pyright: ignore[reportUnknownArgumentType]
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class MetricsSink(Protocol):
    def leadership(self, *, is_leader: bool) -> None: ...

    def failover(self) -> None: ...

    def occurrences(self, status: ExecutionStatus, count: int = 1) -> None: ...

    def dispatch_latency(self, seconds: float) -> None: ...

    def tick_duration(self, seconds: float) -> None: ...


class NoopMetrics:
    def leadership(self, *, is_leader: bool) -> None:
        pass

    def failover(self) -> None:
        pass

    def occurrences(self, status: ExecutionStatus, count: int = 1) -> None:
        pass

    def dispatch_latency(self, seconds: float) -> None:
        pass

    def tick_duration(self, seconds: float) -> None:
        pass
