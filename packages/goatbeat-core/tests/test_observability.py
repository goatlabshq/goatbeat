import json
import logging

import pytest

from goatbeat.core.execution import ExecutionStatus
from goatbeat.core.observability import (
    Event,
    FanoutMetrics,
    JsonFormatter,
    NoopMetrics,
    log_event,
)


def test_log_event_uses_the_event_name_and_structured_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("goatbeat.test")
    with caplog.at_level(logging.INFO, logger="goatbeat.test"):
        log_event(logger, Event.LEASE_ACQUIRED, scheduler_id="a", fencing_token=3)
    [record] = caplog.records
    assert record.getMessage() == "lease.acquired"
    assert record.__dict__["goatbeat"] == {
        "event": "lease.acquired",
        "scheduler_id": "a",
        "fencing_token": 3,
    }


def test_json_formatter_emits_one_parseable_object() -> None:
    record = logging.LogRecord("goatbeat", logging.WARNING, __file__, 1, "leader.lost", None, None)
    record.__dict__["goatbeat"] = {"event": "leader.lost", "scheduler_id": "a"}
    payload = json.loads(JsonFormatter().format(record))
    assert payload["level"] == "WARNING"
    assert payload["logger"] == "goatbeat"
    assert payload["event"] == "leader.lost"
    assert payload["scheduler_id"] == "a"
    assert payload["timestamp"].endswith("+00:00")


def test_json_formatter_includes_exceptions() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        import sys

        record = logging.LogRecord(
            "goatbeat", logging.ERROR, __file__, 1, "submission.failed", None, sys.exc_info()
        )
    payload = json.loads(JsonFormatter().format(record))
    assert "RuntimeError: boom" in payload["exception"]


def test_noop_metrics_accept_every_call() -> None:
    metrics = NoopMetrics()
    metrics.leadership(is_leader=True)
    metrics.failover()
    metrics.occurrences(ExecutionStatus.DISPATCHED, 2)
    metrics.dispatch_latency(0.5)
    metrics.tick_duration(0.01)


def test_fanout_metrics_forward_every_call() -> None:
    calls: list[str] = []

    class Recording(NoopMetrics):
        def occurrences(self, status: ExecutionStatus, count: int = 1) -> None:
            calls.append(f"{status.value}:{count}")

    FanoutMetrics(Recording(), Recording()).occurrences(ExecutionStatus.SKIPPED, 3)
    assert calls == ["skipped:3", "skipped:3"]
