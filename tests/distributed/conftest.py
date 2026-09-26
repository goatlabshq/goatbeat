import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from goatbeat.postgres.provider import PsycopgProvider
from goatbeat.postgres.schema import migrate
from goatbeat.postgres.testing import database_url_from_env, isolated_schema

sys.path.insert(0, str(Path(__file__).parent))

from distributed_support import SpawnWorker

WORKER = Path(__file__).with_name("worker.py")


@pytest.fixture
def conninfo() -> Iterator[str]:
    url = database_url_from_env()
    if url is None:
        pytest.skip("GOATBEAT_TEST_DATABASE_URL is not set")
    with isolated_schema(url) as scoped:
        with PsycopgProvider.connect(scoped) as provider:
            migrate(provider)
        with psycopg.connect(scoped, autocommit=True) as connection:
            connection.execute(
                "CREATE TABLE dispatch_log (idempotency_key text NOT NULL, "
                "schedule_name text NOT NULL, scheduled_at timestamptz NOT NULL, "
                "scheduler_id text NOT NULL, logged_at timestamptz NOT NULL DEFAULT now())"
            )
        yield scoped


@pytest.fixture
def spawn_worker(conninfo: str) -> Iterator[SpawnWorker]:
    processes: list[subprocess.Popen[bytes]] = []

    def spawn(scheduler_id: str) -> subprocess.Popen[bytes]:
        process = subprocess.Popen([sys.executable, str(WORKER), conninfo, scheduler_id])  # noqa: S603
        processes.append(process)
        return process

    yield spawn
    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 10
    for process in processes:
        process.wait(timeout=max(0.1, deadline - time.monotonic()))
