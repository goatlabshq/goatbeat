"""Smoke test run against the built wheels in a clean environment."""

import tempfile
from datetime import timedelta
from pathlib import Path

from goatbeat import CallableSubmitter, GoatbeatConfig, Registry, Scheduler, SQLiteStore
from goatbeat.core.testing import FakeClock

RUNS: list[str] = []


def record() -> None:
    RUNS.append("ran")


def main() -> None:
    clock = FakeClock()
    registry = Registry()
    registry.schedule(name="smoke", task=record, every="1m")
    with tempfile.TemporaryDirectory() as directory, CallableSubmitter() as submitter:
        store = SQLiteStore(Path(directory) / "goatbeat.sqlite3", clock)
        scheduler = Scheduler(
            store=store,
            leases=store,
            submitter=submitter,
            config=GoatbeatConfig(),
            registry=registry,
            clock=clock,
        )
        scheduler.start()
        for _ in range(3):
            clock.advance(timedelta(minutes=1))
            scheduler.tick()
        store.close()
    assert RUNS == ["ran"] * 3, RUNS
    print("goatbeat wheels work: 3 occurrences dispatched")


if __name__ == "__main__":
    main()
