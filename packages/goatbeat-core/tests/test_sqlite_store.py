import sqlite3
import threading
from collections.abc import Iterator
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path

import pytest

from goatbeat.core.errors import LeaseLostError
from goatbeat.core.execution import Lease
from goatbeat.core.ids import SchedulerId
from goatbeat.core.stores.sqlite import SQLiteStore
from goatbeat.core.testing import FakeClock, StoreConformance, StoreUnderTest
from goatbeat.core.testing.conformance import ALICE, TTL, every_minute, one_claim


@pytest.fixture
def opened(tmp_path: Path) -> Iterator[tuple[Path, ExitStack]]:
    with ExitStack() as stack:
        yield tmp_path / "goatbeat.sqlite3", stack


def open_store(opened: tuple[Path, ExitStack], clock: FakeClock) -> SQLiteStore:
    path, stack = opened
    store = SQLiteStore(path, clock)
    stack.callback(store.close)
    return store


class TestSQLiteStore(StoreConformance):
    opened: tuple[Path, ExitStack]

    @pytest.fixture(autouse=True)
    def _opened(self, opened: tuple[Path, ExitStack]) -> None:
        self.opened = opened

    def make_store(self, clock: FakeClock) -> StoreUnderTest:
        store = open_store(self.opened, clock)
        return StoreUnderTest(store=store, leases=store, clock=clock)


def test_schedules_survive_reopening(opened: tuple[Path, ExitStack]) -> None:
    clock = FakeClock()
    saved = open_store(opened, clock).save_schedule(every_minute("job", clock), clock.now())
    assert open_store(opened, clock).get_schedule("job") == saved


def test_concurrent_claims_from_two_connections_create_one_execution(
    opened: tuple[Path, ExitStack],
) -> None:
    clock = FakeClock()
    first, second = open_store(opened, clock), open_store(opened, clock)
    schedule = first.save_schedule(every_minute("job", clock), clock.now())
    lease = first.acquire(ALICE, TTL)
    assert lease is not None
    results: list[int] = []
    barrier = threading.Barrier(8)

    def claim(store: SQLiteStore, held: Lease) -> None:
        barrier.wait()
        results.append(len(store.claim(held, schedule, one_claim(schedule), clock.now())))

    threads = [threading.Thread(target=claim, args=(store, lease)) for store in (first, second) * 4]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == [0] * 7 + [1]
    assert len(first.recent_executions(schedule.id, limit=10)) == 1


def test_a_second_connection_sees_the_takeover(opened: tuple[Path, ExitStack]) -> None:
    clock = FakeClock()
    first, second = open_store(opened, clock), open_store(opened, clock)
    schedule = first.save_schedule(every_minute("job", clock), clock.now())
    stale = first.acquire(ALICE, TTL)
    assert stale is not None
    clock.advance(TTL * 2)
    assert second.acquire(SchedulerId("bob"), TTL) is not None
    with pytest.raises(LeaseLostError):
        first.claim(stale, schedule, one_claim(schedule), clock.now())


def test_an_undecodable_row_is_skipped_instead_of_blocking_the_others(
    opened: tuple[Path, ExitStack], caplog: pytest.LogCaptureFixture
) -> None:
    clock = FakeClock()
    store = open_store(opened, clock)
    store.save_schedule(every_minute("broken", clock), clock.now())
    store.save_schedule(every_minute("healthy", clock), clock.now())
    path, _ = opened
    with sqlite3.connect(path) as raw:
        raw.execute("UPDATE goatbeat_schedule SET trigger_kind = 'solar' WHERE name = 'broken'")
    raw.close()
    due = store.due_schedules(clock.advance(timedelta(minutes=1)), limit=10)
    assert [schedule.name for schedule in due] == ["healthy"]
    assert [schedule.name for schedule in store.list_schedules()] == ["healthy"]
    assert "schedule.invalid" in caplog.text
