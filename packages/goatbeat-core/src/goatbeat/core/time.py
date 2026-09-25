"""Timezone-safe instants and the clock abstraction."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol, Self, overload
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from goatbeat.core.errors import ConfigurationError, NaiveDatetimeError

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND: Final = timedelta(microseconds=1)


@dataclass(frozen=True, slots=True, order=True)
class Instant:
    """A point in time, always stored as an aware UTC datetime."""

    utc: datetime

    def __post_init__(self) -> None:
        if self.utc.tzinfo is None or self.utc.utcoffset() is None:
            raise NaiveDatetimeError(f"naive datetime {self.utc!r} is not an instant")
        if self.utc.tzinfo is not UTC:
            object.__setattr__(self, "utc", self.utc.astimezone(UTC))

    @classmethod
    def of(cls, value: datetime) -> Self:
        return cls(value)

    @classmethod
    def from_timestamp_us(cls, value: int) -> Self:
        return cls(_EPOCH + timedelta(microseconds=value))

    @property
    def datetime(self) -> datetime:
        return self.utc

    @property
    def timestamp_us(self) -> int:
        return (self.utc - _EPOCH) // _MICROSECOND

    def isoformat(self) -> str:
        return self.utc.isoformat()

    def __add__(self, delta: timedelta) -> Instant:
        return Instant(self.utc + delta)

    @overload
    def __sub__(self, other: Instant) -> timedelta: ...
    @overload
    def __sub__(self, other: timedelta) -> Instant: ...
    def __sub__(self, other: Instant | timedelta) -> timedelta | Instant:
        if isinstance(other, Instant):
            return self.utc - other.utc
        return Instant(self.utc - other)


class Clock(Protocol):
    def now(self) -> Instant: ...

    def monotonic(self) -> float: ...


class SystemClock:
    def now(self) -> Instant:
        return Instant(datetime.now(UTC))

    def monotonic(self) -> float:
        return time.monotonic()


def resolve_timezone(value: str | ZoneInfo) -> ZoneInfo:
    if isinstance(value, ZoneInfo):
        return value
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ConfigurationError(f"unknown timezone {value!r}") from error
