import threading
import time
from collections.abc import Iterator
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from goatbeat.core.errors import LeaseLostError, StoreUnavailableError
from goatbeat.core.execution import Lease
from goatbeat.core.ids import SchedulerId
from goatbeat.core.schedule import Schedule
from goatbeat.core.testing import FakeClock, StoreConformance, StoreUnderTest
from goatbeat.core.testing.conformance import ALICE, TTL, every_minute, one_claim
from goatbeat.core.time import Instant
from goatbeat.postgres.provider import PsycopgProvider
from goatbeat.postgres.schema import migrate
from goatbeat.postgres.store import PostgresStore


@pytest.fixture
def provider(conninfo: str) -> Iterator[PsycopgProvider]:
    with PsycopgProvider.connect(conninfo, max_size=8) as opened:
        migrate(opened)
        yield opened


class TestPostgresStore(StoreConformance):
    provider: PsycopgProvider

    @pytest.fixture(autouse=True)
    def _provider(self, provider: PsycopgProvider) -> None:
        self.provider = provider

    def make_store(self, clock: FakeClock) -> StoreUnderTest:
        store = PostgresStore(self.provider, lease_clock=clock)
        return StoreUnderTest(store=store, leases=store, clock=clock)


def test_the_database_clock_decides_lease_expiry(provider: PsycopgProvider) -> None:
    store = PostgresStore(provider)
    assert store.acquire(ALICE, timedelta(seconds=1)) is not None
    assert store.acquire(SchedulerId("bob"), timedelta(seconds=1)) is None
    time.sleep(1.1)
    assert store.acquire(SchedulerId("bob"), timedelta(seconds=1)) is not None


def test_a_takeover_waits_for_an_open_claim_transaction(conninfo: str) -> None:
    clock = FakeClock()
    with ExitStack() as stack:
        first = stack.enter_context(PsycopgProvider.connect(conninfo))
        migrate(first)
        store = PostgresStore(first, lease_clock=clock)
        schedule = store.save_schedule(every_minute("job", clock), clock.now())
        lease = store.acquire(ALICE, TTL)
        assert lease is not None
        clock.advance(TTL - timedelta(seconds=1))
        took_over = threading.Event()

        def take_over() -> None:
            with psycopg.connect(conninfo) as connection:
                connection.execute(
                    "UPDATE goatbeat_lease SET holder_id = 'bob', "
                    "fencing_token = fencing_token + 1 WHERE partition = 0"
                )
            took_over.set()

        with first.transaction() as cursor:
            store.claim_in(cursor, lease, schedule, one_claim(schedule), clock.now())
            thread = threading.Thread(target=take_over)
            thread.start()
            assert not took_over.wait(0.5)  # blocked by the FOR SHARE lock on the lease row
        thread.join(timeout=5)
        assert took_over.is_set()
        with pytest.raises(LeaseLostError):
            store.claim(lease, schedule, one_claim(schedule), clock.now())


def test_microseconds_and_utc_survive_the_round_trip(provider: PsycopgProvider) -> None:
    clock = FakeClock(Instant.of(datetime(2026, 3, 8, 6, 59, 59, 123456, tzinfo=UTC)))
    store = PostgresStore(provider, lease_clock=clock)
    saved = store.save_schedule(every_minute("job", clock), clock.now())
    loaded = store.get_schedule("job")
    assert loaded == saved
    assert loaded is not None
    assert loaded.next_run_at.datetime.tzinfo is UTC


def test_an_undecodable_row_is_skipped(
    provider: PsycopgProvider, conninfo: str, caplog: pytest.LogCaptureFixture
) -> None:
    clock = FakeClock()
    store = PostgresStore(provider, lease_clock=clock)
    store.save_schedule(every_minute("broken", clock), clock.now())
    store.save_schedule(every_minute("healthy", clock), clock.now())
    with psycopg.connect(conninfo) as connection:
        connection.execute(
            "UPDATE goatbeat_schedule SET timezone = 'Mars/Base', cron = '* * * * *', "
            "trigger_kind = 'cron' WHERE name = 'broken'"
        )
    due = store.due_schedules(clock.advance(timedelta(minutes=1)), limit=10)
    assert [schedule.name for schedule in due] == ["healthy"]
    assert "schedule.invalid" in caplog.text


def test_ten_connections_claiming_one_occurrence_create_one_execution(conninfo: str) -> None:
    clock = FakeClock()
    with PsycopgProvider.connect(conninfo, min_size=10, max_size=10) as provider:
        migrate(provider)
        store = PostgresStore(provider, lease_clock=clock)
        schedule = store.save_schedule(every_minute("job", clock), clock.now())
        lease = store.acquire(ALICE, TTL)
        assert lease is not None
        barrier = threading.Barrier(10)
        created: list[int] = []

        def claim() -> None:
            barrier.wait()
            created.append(len(store.claim(lease, schedule, one_claim(schedule), clock.now())))

        threads = [threading.Thread(target=claim) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(created) == [0] * 9 + [1]
        assert len(store.recent_executions(schedule.id, limit=20)) == 1


def test_a_frozen_fence_holder_cannot_block_lease_acquisition(conninfo: str) -> None:
    with ExitStack() as stack:
        frozen = stack.enter_context(PsycopgProvider.connect(conninfo))
        other = stack.enter_context(PsycopgProvider.connect(conninfo))
        migrate(frozen)
        clock = FakeClock()
        store = PostgresStore(frozen, lease_clock=clock)
        schedule = store.save_schedule(every_minute("job", clock), clock.now())
        lease = store.acquire(ALICE, TTL)
        assert lease is not None
        standby = PostgresStore(other, lease_clock=clock, lock_timeout=timedelta(milliseconds=500))
        with frozen.transaction() as cursor:
            store.claim_in(cursor, lease, schedule, one_claim(schedule), clock.now())
            clock.advance(TTL * 2)
            started = time.monotonic()
            with pytest.raises(StoreUnavailableError):
                standby.acquire(SchedulerId("bob"), TTL)
            assert time.monotonic() - started < 3


def claim_then_freeze(
    provider: PsycopgProvider,
    store: PostgresStore,
    lease: Lease,
    schedule: Schedule,
    clock: FakeClock,
) -> None:
    with provider.transaction() as cursor:
        store.claim_in(cursor, lease, schedule, one_claim(schedule), clock.now())
        time.sleep(1.5)


def test_the_database_ends_a_fence_holder_that_stays_idle(conninfo: str) -> None:
    clock = FakeClock()
    with ExitStack() as stack:
        frozen = stack.enter_context(PsycopgProvider.connect(conninfo))
        other = stack.enter_context(PsycopgProvider.connect(conninfo))
        migrate(frozen)
        store = PostgresStore(
            frozen, lease_clock=clock, fence_idle_timeout=timedelta(milliseconds=500)
        )
        schedule = store.save_schedule(every_minute("job", clock), clock.now())
        lease = store.acquire(ALICE, TTL)
        assert lease is not None
        with pytest.raises(StoreUnavailableError):
            claim_then_freeze(frozen, store, lease, schedule, clock)
        clock.advance(TTL * 2)
        assert PostgresStore(other, lease_clock=clock).acquire(SchedulerId("bob"), TTL)


def test_schedulers_starting_together_sync_without_conflicts(conninfo: str) -> None:
    clock = FakeClock()
    definitions = [every_minute(f"job-{index:02}", clock) for index in range(20)]
    with PsycopgProvider.connect(conninfo, min_size=8, max_size=8) as provider:
        migrate(provider)
        barrier = threading.Barrier(8)
        errors: list[BaseException] = []

        def start(order: int) -> None:
            ordered = definitions[order:] + definitions[:order]  # versions list them differently
            barrier.wait()
            try:
                PostgresStore(provider).sync_code_schedules(ordered, clock.now())
            except BaseException as error:
                errors.append(error)

        threads = [threading.Thread(target=start, args=(order,)) for order in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []
        assert len(PostgresStore(provider).list_schedules()) == 20
