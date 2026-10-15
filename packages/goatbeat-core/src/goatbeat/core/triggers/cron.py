import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Self
from zoneinfo import ZoneInfo

from goatbeat.core.time import Instant, resolve_timezone
from goatbeat.core.triggers.cron_expression import CronExpression

# DST shifts never exceed two hours, so this window catches every reordered wall time.
_DST_WINDOW: Final = timedelta(hours=3)


@dataclass(frozen=True, slots=True)
class CronTrigger:
    """Fixed-hour jobs run once across DST changes; wildcard-hour jobs follow real time."""

    expression: CronExpression
    timezone: ZoneInfo

    @classmethod
    def parse(cls, expression: str, timezone: str | ZoneInfo) -> Self:
        return cls(CronExpression.parse(expression), resolve_timezone(timezone))

    def next_after(self, instant: Instant) -> Instant:
        local = instant.datetime.astimezone(self.timezone).replace(tzinfo=None)
        window = _DST_WINDOW if self._near_transition(instant) else timedelta(0)
        wall = local - window
        best: Instant | None = None
        horizon = datetime.max  # noqa: DTZ901 (naive wall-clock bound)
        while True:
            wall = self.expression.next_wall_time(wall)
            if best is not None and wall > horizon:
                return best
            for candidate in self._instants_at(wall):
                if candidate > instant and (best is None or candidate < best):
                    horizon = min(horizon, wall + window)
                    best = candidate
            if best is not None and not window:
                return best

    def _near_transition(self, instant: Instant) -> bool:
        before = (instant - _DST_WINDOW).datetime.astimezone(self.timezone).utcoffset()
        after = (instant + _DST_WINDOW).datetime.astimezone(self.timezone).utcoffset()
        return before != after

    def _instants_at(self, wall: datetime) -> list[Instant]:
        first = wall.replace(tzinfo=self.timezone, fold=0).astimezone(UTC)
        second = wall.replace(tzinfo=self.timezone, fold=1).astimezone(UTC)
        if first == second:
            return [Instant(first)]
        repeated = first < second
        if self.expression.hour_is_wildcard:
            return [Instant(first), Instant(second)] if repeated else []
        return [Instant(first)] if repeated else [self._gap_end(second, first)]

    def _gap_end(self, before: datetime, after: datetime) -> Instant:
        """Bisect whole seconds: tzdata transitions always fall on a whole second."""
        offset_before = before.astimezone(self.timezone).utcoffset()
        low, high = math.floor(before.timestamp()), math.ceil(after.timestamp())
        while high - low > 1:
            middle = (low + high) // 2
            if datetime.fromtimestamp(middle, self.timezone).utcoffset() == offset_before:
                low = middle
            else:
                high = middle
        return Instant(datetime.fromtimestamp(high, UTC))
