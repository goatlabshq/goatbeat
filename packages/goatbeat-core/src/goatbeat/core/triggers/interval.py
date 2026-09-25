"""Fixed-rate schedules anchored on a start instant."""

from dataclasses import dataclass
from datetime import timedelta

from goatbeat.core.errors import InvalidIntervalError
from goatbeat.core.time import Instant


@dataclass(frozen=True, slots=True)
class IntervalTrigger:
    """Fires at ``start_at + k * every``, so delays never accumulate into drift."""

    every: timedelta
    start_at: Instant

    def __post_init__(self) -> None:
        if self.every <= timedelta(0):
            raise InvalidIntervalError(f"interval must be positive, got {self.every}")

    def next_after(self, instant: Instant) -> Instant:
        if instant < self.start_at:
            return self.start_at
        elapsed_steps = (instant - self.start_at) // self.every
        return self.start_at + self.every * (elapsed_steps + 1)
