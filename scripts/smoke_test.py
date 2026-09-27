"""Smoke test run against the built wheels in a clean environment."""

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

from goatbeat import (
    CallableSubmitter,
    GoatbeatApp,
    GoatbeatConfig,
    Registry,
    Scheduler,
    SQLiteStore,
)
from goatbeat.core.testing import FakeClock

RUNS: list[str] = []


def record() -> None:
    RUNS.append("ran")


beat = Registry()
beat.schedule(name="smoke", task=record, every="1m")
app = GoatbeatApp(registry=beat, submitter=CallableSubmitter())


def library(directory: str) -> None:
    clock = FakeClock()
    store = SQLiteStore(Path(directory) / "library.sqlite3", clock)
    scheduler = Scheduler(
        store=store,
        leases=store,
        submitter=app.submitter,
        config=GoatbeatConfig(),
        registry=beat,
        clock=clock,
    )
    scheduler.start()
    for _ in range(3):
        clock.advance(timedelta(minutes=1))
        scheduler.tick()
    store.close()
    assert RUNS == ["ran"] * 3, RUNS


def command_line(directory: str) -> None:
    executable = shutil.which("goatbeat", path=str(Path(sys.executable).parent))
    assert executable is not None, "the goatbeat console script is not installed"
    environment = os.environ | {
        "GOATBEAT_DATABASE_URL": f"sqlite:///{Path(directory) / 'cli.sqlite3'}",
        "PYTHONPATH": str(Path(__file__).parent),
    }
    for command in (["doctor"], ["scheduler", "--once"], ["status", "--json"]):
        subprocess.run(  # noqa: S603
            [executable, "--app", "smoke_test:app", *command], env=environment, check=True
        )


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        library(directory)
        command_line(directory)
    print("goatbeat wheels work: library and command line")


if __name__ == "__main__":
    main()
