import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Final

import psycopg
import pytest

from goatbeat.core.config import GoatbeatConfig
from goatbeat.core.execution import SubmissionReceipt
from goatbeat.core.ids import SchedulerId
from goatbeat.core.scheduler import Scheduler
from goatbeat.core.submission import TaskSubmission
from goatbeat.core.time import Instant, SystemClock
from goatbeat.postgres.provider import PsycopgProvider
from goatbeat.postgres.schema import migrate
from goatbeat.postgres.store import DUE_SCHEDULES_QUERY, PostgresStore
from goatbeat.postgres.testing import database_url_from_env, isolated_schema

pytestmark = pytest.mark.performance

SCHEDULES: Final = 1_000_000 if os.environ.get("GOATBEAT_PERF_FULL") == "1" else 100_000
DUE_NOW: Final = 500
BATCH: Final = 500


class NoopBackend:
    def submit(self, submission: TaskSubmission) -> SubmissionReceipt:
        return SubmissionReceipt(submission.idempotency_key.value)


@pytest.fixture(scope="module")
def conninfo() -> Iterator[str]:
    url = database_url_from_env()
    if url is None:
        pytest.skip("GOATBEAT_TEST_DATABASE_URL is not set")
    with isolated_schema(url) as scoped:
        with PsycopgProvider.connect(scoped) as provider:
            migrate(provider)
        with psycopg.connect(scoped) as connection:
            # DUE_NOW schedules are overdue; the rest are spread over the next day.
            connection.execute(
                "INSERT INTO goatbeat_schedule (id, name, source, task_path, task_args, "
                "task_kwargs, trigger_kind, interval_us, start_at, cron, timezone, "
                "misfire_policy, misfire_grace_us, max_catch_up, queue, priority, backend, "
                "enabled, next_run_at) "
                "SELECT 'perf-' || n, 'perf-' || n, 'store', 'perf.noop', '[]', '{}', "
                "'interval', 86400000000, '1970-01-01T00:00:00Z', NULL, NULL, 'run_once', "
                "60000000, 100, NULL, NULL, NULL, n %% 10 <> 0, "
                "CASE WHEN n <= %s THEN now() - interval '1 second' "
                "ELSE now() + (n || ' seconds')::interval * 86400 / %s END "
                "FROM generate_series(1, %s) AS n",
                [DUE_NOW * 10 // 9, SCHEDULES, SCHEDULES],
            )
            connection.execute("ANALYZE goatbeat_schedule")
        yield scoped


def test_due_query_uses_the_partial_index(conninfo: str) -> None:
    with psycopg.connect(conninfo) as connection:
        rows = connection.execute(
            "EXPLAIN " + DUE_SCHEDULES_QUERY, [datetime.now(UTC), BATCH]
        ).fetchall()
    plan = "\n".join(str(row[0]) for row in rows)
    assert "goatbeat_schedule_due" in plan
    assert "Seq Scan" not in plan


def test_due_query_latency(conninfo: str) -> None:
    with PsycopgProvider.connect(conninfo) as provider:
        store = PostgresStore(provider)
        now = Instant.of(datetime.now(UTC))
        due = store.due_schedules(now, BATCH)
        started = time.perf_counter()
        for _ in range(20):
            due = store.due_schedules(now, BATCH)
        elapsed = (time.perf_counter() - started) / 20
    print(f"due query over {SCHEDULES} schedules: {elapsed * 1000:.1f} ms for {len(due)} rows")
    assert len(due) == DUE_NOW
    assert elapsed < 0.25


def test_a_tick_claims_and_dispatches_a_full_batch(conninfo: str) -> None:
    with PsycopgProvider.connect(conninfo, max_size=4) as provider:
        store = PostgresStore(provider)
        scheduler = Scheduler(
            store=store,
            leases=store,
            submitter=NoopBackend(),
            config=GoatbeatConfig(
                scheduler_id=SchedulerId("perf"), batch_size=BATCH, max_sleep=timedelta(seconds=5)
            ),
            clock=SystemClock(),
        )
        started = time.perf_counter()
        scheduler.tick()
        elapsed = time.perf_counter() - started
        dispatched = store.recent_executions(None, limit=DUE_NOW + 1)
    print(f"tick over {SCHEDULES} schedules: {elapsed:.2f} s for {len(dispatched)} dispatches")
    assert len(dispatched) == DUE_NOW
    assert elapsed < 20
