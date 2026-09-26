import signal
import time
from collections.abc import Callable
from datetime import datetime

import psycopg
import pytest
from distributed_support import SpawnWorker

pytestmark = pytest.mark.distributed

TTL_SECONDS = 5
RENEW_SECONDS = 1


def leader(conninfo: str) -> str | None:
    with psycopg.connect(conninfo) as connection:
        row = connection.execute(
            "SELECT holder_id FROM goatbeat_lease WHERE partition = 0 AND expires_at > now()"
        ).fetchone()
    return None if row is None else row[0]


def dispatches_since(conninfo: str, moment: datetime) -> list[tuple[str, str, datetime]]:
    with psycopg.connect(conninfo) as connection:
        return connection.execute(
            "SELECT idempotency_key, scheduler_id, logged_at FROM dispatch_log "
            "WHERE logged_at > %s ORDER BY logged_at",
            [moment],
        ).fetchall()


def wait_for(condition: Callable[[], bool], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.1)
    raise AssertionError("condition not met in time")


def database_now(conninfo: str) -> datetime:
    with psycopg.connect(conninfo) as connection:
        row = connection.execute("SELECT now()").fetchone()
    assert row is not None
    return row[0]


def test_a_standby_takes_over_after_the_leader_is_killed(
    conninfo: str, spawn_worker: SpawnWorker
) -> None:
    workers = {name: spawn_worker(name) for name in ("alpha", "beta", "gamma")}
    started = database_now(conninfo)
    wait_for(lambda: leader(conninfo) is not None and bool(dispatches_since(conninfo, started)), 15)
    killed = leader(conninfo)
    assert killed is not None
    killed_at = database_now(conninfo)
    workers[killed].send_signal(signal.SIGKILL)
    workers[killed].wait(timeout=5)
    wait_for(
        lambda: any(row[1] != killed for row in dispatches_since(conninfo, killed_at)),
        TTL_SECONDS + RENEW_SECONDS + 5,
    )
    first_new = next(row for row in dispatches_since(conninfo, killed_at) if row[1] != killed)
    failover = (first_new[2] - killed_at).total_seconds()
    assert failover < TTL_SECONDS + RENEW_SECONDS + 3
    time.sleep(2)
    with psycopg.connect(conninfo) as connection:
        duplicated = connection.execute(
            "SELECT idempotency_key FROM dispatch_log GROUP BY 1 HAVING count(*) > 1"
        ).fetchall()
    # A kill between a submission and its bookkeeping resubmits that key (at least once):
    # at most one per schedule.
    assert len(duplicated) <= 2
