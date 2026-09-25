from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from goatbeat.core.errors import NaiveDatetimeError
from goatbeat.core.time import Instant, SystemClock


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(NaiveDatetimeError):
        Instant.of(datetime(2026, 1, 1, 12, 0))  # noqa: DTZ001


def test_aware_datetime_is_normalized_to_utc_without_moving_the_instant() -> None:
    paris = datetime(2026, 7, 1, 12, 0, tzinfo=ZoneInfo("Europe/Paris"))
    instant = Instant.of(paris)
    assert instant.datetime == datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    assert instant.datetime.tzinfo is UTC


def test_microsecond_timestamp_round_trip() -> None:
    instant = Instant.of(datetime(2026, 3, 8, 7, 0, 0, 123456, tzinfo=UTC))
    assert Instant.from_timestamp_us(instant.timestamp_us) == instant


def test_arithmetic_and_ordering() -> None:
    start = Instant.of(datetime(2026, 1, 1, tzinfo=UTC))
    later = start + timedelta(minutes=5)
    assert later - start == timedelta(minutes=5)
    assert later - timedelta(minutes=5) == start
    assert start < later
    assert later.isoformat() == "2026-01-01T00:05:00+00:00"


def test_system_clock_returns_utc_instant() -> None:
    clock = SystemClock()
    assert clock.now().datetime.tzinfo is UTC
    assert clock.monotonic() <= clock.monotonic()
