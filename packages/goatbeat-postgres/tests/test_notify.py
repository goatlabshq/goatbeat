import threading
import time
from datetime import timedelta

from goatbeat.core.testing import FakeClock
from goatbeat.core.testing.conformance import every_minute
from goatbeat.postgres.notify import PsycopgNotifier
from goatbeat.postgres.provider import PsycopgProvider
from goatbeat.postgres.schema import migrate
from goatbeat.postgres.store import PostgresStore


def test_a_schedule_change_wakes_a_waiting_scheduler(conninfo: str) -> None:
    clock = FakeClock()
    with PsycopgProvider.connect(conninfo) as provider, PsycopgNotifier(conninfo) as notifier:
        migrate(provider)
        waiting = PostgresStore(provider, notifier=notifier)
        writer = PostgresStore(provider)
        assert not waiting.wait_for_change(timedelta(milliseconds=50))
        timer = threading.Timer(
            0.2, lambda: writer.save_schedule(every_minute("job", clock), clock.now())
        )
        started = time.monotonic()
        timer.start()
        assert waiting.wait_for_change(timedelta(seconds=5))
        assert time.monotonic() - started < 2
        timer.join()


def test_waiting_times_out_without_notification(conninfo: str) -> None:
    with PsycopgNotifier(conninfo) as notifier:
        started = time.monotonic()
        assert not notifier.wait(timedelta(milliseconds=200))
        assert 0.15 < time.monotonic() - started < 2


def test_an_unreachable_database_degrades_to_a_plain_timeout() -> None:
    unreachable = "postgresql://nobody@127.0.0.1:1/none?connect_timeout=1"
    with PsycopgNotifier(unreachable) as notifier:
        assert not notifier.wait(timedelta(milliseconds=100))


def test_an_unroutable_host_does_not_stall_the_wait() -> None:
    blackhole = "postgresql://nobody@10.255.255.1:5432/none"
    with PsycopgNotifier(blackhole) as notifier:
        started = time.monotonic()
        assert not notifier.wait(timedelta(seconds=1))
        assert time.monotonic() - started < 4
