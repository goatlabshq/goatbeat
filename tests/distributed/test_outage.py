import os
import subprocess
import time
from datetime import UTC, datetime

import psycopg
import pytest
from distributed_support import SpawnWorker

pytestmark = [
    pytest.mark.distributed,
    pytest.mark.skipif(
        os.environ.get("GOATBEAT_TEST_CAN_RESTART_DATABASE") != "1",
        reason="stops the docker compose postgres service",
    ),
]

OUTAGE_SECONDS = 4


def compose(*arguments: str) -> None:
    subprocess.run(  # noqa: S603
        ["docker", "compose", *arguments, "postgres"],  # noqa: S607
        check=True,
        capture_output=True,
    )


def dispatched_after(conninfo: str, moment: datetime) -> int:
    with psycopg.connect(conninfo) as connection:
        row = connection.execute(
            "SELECT count(*) FROM dispatch_log WHERE logged_at > %s", [moment]
        ).fetchone()
    assert row is not None
    return row[0]


def test_scheduling_resumes_after_postgresql_comes_back(
    conninfo: str, spawn_worker: SpawnWorker
) -> None:
    worker = spawn_worker("survivor")
    time.sleep(4)
    assert dispatched_after(conninfo, datetime.min.replace(tzinfo=UTC)) > 0
    compose("stop")
    time.sleep(OUTAGE_SECONDS)
    compose("start")
    compose("up", "--wait")
    back = datetime.now(UTC)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and dispatched_after(conninfo, back) == 0:
        time.sleep(0.5)
    assert dispatched_after(conninfo, back) > 0, "no dispatch after the database came back"
    assert worker.poll() is None, "the scheduler process died during the outage"
