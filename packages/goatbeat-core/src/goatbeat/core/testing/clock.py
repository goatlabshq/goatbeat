"""A deterministic clock for tests."""

from datetime import UTC, datetime, timedelta

from goatbeat.core.time import Instant

DEFAULT_START = Instant.of(datetime(2026, 1, 1, tzinfo=UTC))


class FakeClock:
    def __init__(self, start: Instant = DEFAULT_START) -> None:
        self._start = start
        self._now = start

    def now(self) -> Instant:
        return self._now

    def monotonic(self) -> float:
        return (self._now - self._start).total_seconds()

    def advance(self, delta: timedelta) -> Instant:
        self._now = self._now + delta
        return self._now

    def set(self, instant: Instant) -> None:
        if instant < self._now:
            raise ValueError("a FakeClock never goes backwards")
        self._now = instant
