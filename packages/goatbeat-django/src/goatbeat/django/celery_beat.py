import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, cast

from goatbeat.core.errors import ConfigurationError, NaiveDatetimeError
from goatbeat.core.json import JsonValue, ensure_json
from goatbeat.core.misfire import MisfireRules
from goatbeat.core.registry import DEFAULT_INTERVAL_ANCHOR
from goatbeat.core.schedule import Routing, ScheduleDefinition
from goatbeat.core.tasks import TaskCall
from goatbeat.core.time import Instant
from goatbeat.core.triggers import CronTrigger, IntervalTrigger, Trigger

PERIODS: Final = {
    "days": timedelta(days=1),
    "hours": timedelta(hours=1),
    "minutes": timedelta(minutes=1),
    "seconds": timedelta(seconds=1),
    "microseconds": timedelta(microseconds=1),
}
EMPTY_HEADERS: Final = ("", "{}")

LEGACY_QUERY: Final = (
    "SELECT t.name, t.task, t.args, t.kwargs, t.queue, t.priority, t.enabled, t.one_off, "
    "t.start_time, t.expires, t.expire_seconds, t.exchange, t.routing_key, t.headers, "
    "i.every, i.period, c.minute, c.hour, c.day_of_month, c.month_of_year, c.day_of_week, "
    "c.timezone, t.solar_id IS NOT NULL, t.clocked_id IS NOT NULL "
    "FROM django_celery_beat_periodictask t "
    "LEFT JOIN django_celery_beat_intervalschedule i ON i.id = t.interval_id "
    "LEFT JOIN django_celery_beat_crontabschedule c ON c.id = t.crontab_id "
    "ORDER BY t.name"
)


@dataclass(frozen=True, slots=True)
class Interval:
    every: int
    period: str


@dataclass(frozen=True, slots=True)
class Crontab:
    minute: str
    hour: str
    day_of_month: str
    month_of_year: str
    day_of_week: str
    timezone: str

    @property
    def expression(self) -> str:
        return " ".join(
            (self.minute, self.hour, self.day_of_month, self.month_of_year, self.day_of_week)
        )


@dataclass(frozen=True, slots=True)
class LegacyTask:
    name: str
    task: str
    args: str
    kwargs: str
    queue: str | None
    priority: int | None
    enabled: bool
    one_off: bool
    start_time: datetime | None
    expires: datetime | None
    expire_seconds: int | None
    exchange: str | None
    routing_key: str | None
    headers: str | None
    interval: Interval | None
    crontab: Crontab | None
    solar: bool
    clocked: bool


@dataclass(frozen=True, slots=True)
class Conversion:
    name: str
    definition: ScheduleDefinition | None
    notes: tuple[str, ...]


class SkipError(Exception):
    pass


def no_routing_problem(path: str, routing: Routing) -> str | None:
    del path, routing
    return None


def convert(
    legacy: LegacyTask,
    *,
    task_exists: Callable[[str], bool],
    routing_problem: Callable[[str, Routing], str | None] = no_routing_problem,
) -> Conversion:
    try:
        trigger = _trigger(legacy)
        args, kwargs = _arguments(legacy)
        routing = Routing(queue=legacy.queue or None, priority=legacy.priority)
        notes = _unsupported_options(legacy)
        enabled = legacy.enabled
        if not task_exists(legacy.task):
            enabled = False
            notes.append(f"{legacy.task} is not a Django task: imported disabled, port it first")
        elif problem := routing_problem(legacy.task, routing):
            enabled = False
            notes.append(f"routing refused ({problem}): imported disabled, fix it in the admin")
        definition = ScheduleDefinition(
            name=legacy.name,
            task=TaskCall(legacy.task, tuple(args), kwargs),
            trigger=trigger,
            misfire=MisfireRules(),
            routing=routing,
            enabled=enabled,
        )
    except SkipError as skip:
        return Conversion(legacy.name, None, (str(skip),))
    except (ConfigurationError, OverflowError, ValueError) as error:
        return Conversion(legacy.name, None, (f"rejected: {error}",))
    return Conversion(legacy.name, definition, tuple(notes))


def read_legacy(rows: Sequence[Sequence[object]]) -> list[LegacyTask]:
    return [_legacy_task(row) for row in rows]


def _legacy_task(row: Sequence[object]) -> LegacyTask:
    every, period = row[14], row[15]
    crontab = None
    if row[16] is not None:
        minute, hour, day, month, weekday = (str(value or "*") for value in row[16:21])
        crontab = Crontab(minute, hour, day, month, weekday, str(row[21] or "UTC"))
    return LegacyTask(
        name=str(row[0]),
        task=str(row[1]),
        args=str(row[2] or "[]"),
        kwargs=str(row[3] or "{}"),
        queue=cast("str | None", row[4]),
        priority=cast("int | None", row[5]),
        enabled=bool(row[6]),
        one_off=bool(row[7]),
        start_time=cast("datetime | None", row[8]),
        expires=cast("datetime | None", row[9]),
        expire_seconds=cast("int | None", row[10]),
        exchange=cast("str | None", row[11]),
        routing_key=cast("str | None", row[12]),
        headers=cast("str | None", row[13]),
        interval=None if every is None else Interval(int(str(every)), str(period)),
        crontab=crontab,
        solar=bool(row[22]),
        clocked=bool(row[23]),
    )


def _trigger(legacy: LegacyTask) -> Trigger:
    if legacy.solar:
        raise SkipError("solar schedules have no Goatbeat equivalent")
    if legacy.clocked:
        raise SkipError("clocked (one-time) schedules have no Goatbeat equivalent")
    if legacy.crontab is not None:
        if "*" not in (legacy.crontab.day_of_month, legacy.crontab.day_of_week):
            raise SkipError(
                "celery matches day of month and day of week together, cron matches either: "
                "split it into two schedules"
            )
        try:
            return CronTrigger.parse(legacy.crontab.expression, legacy.crontab.timezone)
        except ConfigurationError as error:
            kind = "timezone" if "timezone" in str(error) else "cron"
            raise SkipError(f"invalid {kind}: {error}") from error
    if legacy.interval is not None:
        unit = PERIODS.get(legacy.interval.period)
        if unit is None or legacy.interval.every <= 0:
            raise SkipError(f"invalid interval {legacy.interval}")
        try:
            anchor = (
                DEFAULT_INTERVAL_ANCHOR
                if legacy.start_time is None
                else Instant.of(legacy.start_time)
            )
        except NaiveDatetimeError as error:
            raise SkipError(f"naive start_time: {error}") from error
        return IntervalTrigger(unit * legacy.interval.every, anchor)
    raise SkipError("no schedule attached")


def _arguments(legacy: LegacyTask) -> tuple[list[JsonValue], dict[str, JsonValue]]:
    try:
        args = ensure_json(json.loads(legacy.args))
        kwargs = ensure_json(json.loads(legacy.kwargs))
    except (ValueError, ConfigurationError) as error:
        raise SkipError(f"unreadable arguments: {error}") from error
    if not isinstance(args, list) or not isinstance(kwargs, dict):
        raise SkipError("arguments must be a JSON array and a JSON object")
    return args, kwargs


def _unsupported_options(legacy: LegacyTask) -> list[str]:
    ignored = {
        "one_off": legacy.one_off,
        "expires": legacy.expires is not None,
        "expire_seconds": legacy.expire_seconds is not None,
        "start_time": legacy.crontab is not None and legacy.start_time is not None,
        "exchange": bool(legacy.exchange),
        "routing_key": bool(legacy.routing_key),
        "headers": (legacy.headers or "").strip() not in EMPTY_HEADERS,
    }
    return [
        f"{option} is not supported and was dropped" for option, used in ignored.items() if used
    ]
