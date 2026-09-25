"""Five-field cron expressions evaluated on naive wall-clock time."""

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final, Self

from goatbeat.core.errors import InvalidCronExpressionError

_FIELD_COUNT: Final = 5
_ALL_HOURS: Final = frozenset(range(24))
_MAX_DAYS_IN_MONTH: Final = dict(enumerate((31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31), 1))
# A satisfiable expression matches within one leap cycle, including the 2096 -> 2104 gap.
_SEARCH_HORIZON: Final = timedelta(days=366 * 9)
_MONTH_NAMES: Final = {
    name.lower(): number for number, name in enumerate(calendar.month_abbr) if name
}
_WEEKDAY_NAMES: Final = {
    "sun": 0,
    "mon": 1,
    "tue": 2,
    "wed": 3,
    "thu": 4,
    "fri": 5,
    "sat": 6,
}


@dataclass(frozen=True, slots=True)
class _FieldSpec:
    name: str
    low: int
    high: int
    names: dict[str, int]


_MINUTE: Final = _FieldSpec("minute", 0, 59, {})
_HOUR: Final = _FieldSpec("hour", 0, 23, {})
_DAY: Final = _FieldSpec("day of month", 1, 31, {})
_MONTH: Final = _FieldSpec("month", 1, 12, _MONTH_NAMES)
_WEEKDAY: Final = _FieldSpec("day of week", 0, 7, _WEEKDAY_NAMES)


@dataclass(frozen=True, slots=True)
class CronExpression:
    text: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    day_restricted: bool
    weekday_restricted: bool

    @classmethod
    def parse(cls, text: str) -> Self:
        fields = text.split()
        if len(fields) != _FIELD_COUNT:
            raise InvalidCronExpressionError(
                f"{text!r} must have {_FIELD_COUNT} fields, got {len(fields)}"
            )
        minute, hour, day, month, weekday = fields
        expression = cls(
            text=text,
            minutes=_parse_field(minute, _MINUTE),
            hours=_parse_field(hour, _HOUR),
            days=_parse_field(day, _DAY),
            months=_parse_field(month, _MONTH),
            weekdays=frozenset(value % 7 for value in _parse_field(weekday, _WEEKDAY)),
            day_restricted=not day.startswith("*"),
            weekday_restricted=not weekday.startswith("*"),
        )
        expression._ensure_satisfiable()
        return expression

    @property
    def hour_is_wildcard(self) -> bool:
        return self.hours == _ALL_HOURS

    def matches_date(self, day: date) -> bool:
        day_matches = day.day in self.days
        weekday_matches = (day.weekday() + 1) % 7 in self.weekdays
        if self.day_restricted and self.weekday_restricted:
            return day_matches or weekday_matches
        return day_matches and weekday_matches

    def next_wall_time(self, after: datetime) -> datetime:
        """Return the first matching naive wall time strictly after ``after``."""
        candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
        deadline = candidate + _SEARCH_HORIZON
        while candidate < deadline:
            if candidate.month not in self.months:
                candidate = _first_day_of_next_month(candidate)
            elif not self.matches_date(candidate.date()):
                candidate = _next_day(candidate)
            elif candidate.hour not in self.hours:
                candidate = candidate.replace(minute=0) + timedelta(hours=1)
            elif candidate.minute not in self.minutes:
                candidate = self._next_minute(candidate)
            else:
                return candidate
        raise InvalidCronExpressionError(f"{self.text!r} never matches")

    def _next_minute(self, candidate: datetime) -> datetime:
        later = [minute for minute in self.minutes if minute > candidate.minute]
        if later:
            return candidate.replace(minute=min(later))
        return candidate.replace(minute=0) + timedelta(hours=1)

    def _ensure_satisfiable(self) -> None:
        if self.weekday_restricted:
            return
        if not any(day <= _MAX_DAYS_IN_MONTH[month] for month in self.months for day in self.days):
            raise InvalidCronExpressionError(f"{self.text!r} never matches")


def _first_day_of_next_month(moment: datetime) -> datetime:
    if moment.month == 12:
        return datetime(moment.year + 1, 1, 1)  # noqa: DTZ001
    return datetime(moment.year, moment.month + 1, 1)  # noqa: DTZ001


def _next_day(moment: datetime) -> datetime:
    return datetime(moment.year, moment.month, moment.day) + timedelta(days=1)  # noqa: DTZ001


def _parse_field(text: str, spec: _FieldSpec) -> frozenset[int]:
    values: set[int] = set()
    for element in text.split(","):
        values.update(_parse_element(element, spec))
    return frozenset(values)


def _parse_element(element: str, spec: _FieldSpec) -> range:
    base, slash, step_text = element.partition("/")
    step = _parse_number(step_text, spec, allow_names=False) if slash else 1
    if step <= 0:
        raise InvalidCronExpressionError(f"step must be positive in {spec.name} {element!r}")
    if base == "*":
        return range(spec.low, spec.high + 1, step)
    start_text, dash, end_text = base.partition("-")
    start = _parse_number(start_text, spec, allow_names=True)
    if dash:
        end = _parse_number(end_text, spec, allow_names=True)
    elif slash:
        end = spec.high
    else:
        end = start
    if not spec.low <= start <= end <= spec.high:
        raise InvalidCronExpressionError(
            f"{spec.name} {element!r} is outside {spec.low}-{spec.high} or reversed"
        )
    return range(start, end + 1, step)


def _parse_number(text: str, spec: _FieldSpec, *, allow_names: bool) -> int:
    lowered = text.lower()
    if allow_names and lowered in spec.names:
        return spec.names[lowered]
    if not (text.isascii() and text.isdigit()):
        raise InvalidCronExpressionError(f"invalid {spec.name} value {text!r}")
    return int(text)
