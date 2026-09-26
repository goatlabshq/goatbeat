import time
from datetime import datetime, timedelta

import psycopg
import pytest
from distributed_support import SpawnWorker

pytestmark = pytest.mark.distributed

RUN_SECONDS = 8


def dispatches(conninfo: str) -> list[tuple[str, str, datetime, str]]:
    with psycopg.connect(conninfo) as connection:
        return connection.execute(
            "SELECT idempotency_key, schedule_name, scheduled_at, scheduler_id FROM dispatch_log "
            "ORDER BY scheduled_at"
        ).fetchall()


def missing_seconds(times: list[datetime]) -> list[datetime]:
    expected = {times[0] + timedelta(seconds=step) for step in range(len(times))}
    wanted = set(times)
    last = max(times)
    return sorted(moment for moment in expected - wanted if moment <= last)


def test_ten_schedulers_dispatch_each_occurrence_exactly_once(
    conninfo: str, spawn_worker: SpawnWorker
) -> None:
    workers = [spawn_worker(f"worker-{index}") for index in range(10)]
    time.sleep(RUN_SECONDS)
    for worker in workers:
        worker.terminate()
    for worker in workers:
        assert worker.wait(timeout=10) == 0
    rows = dispatches(conninfo)
    keys = [row[0] for row in rows]
    assert len(keys) >= 2 * (RUN_SECONDS - 3)
    assert len(keys) == len(set(keys)), "an occurrence was dispatched twice"
    for name in ("every-second-a", "every-second-b"):
        times = sorted(row[2] for row in rows if row[1] == name)
        assert missing_seconds(times) == [], f"{name} skipped occurrences"
    assert len({row[3] for row in rows}) == 1, "leadership should not flap without failures"
