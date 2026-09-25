"""The typed, explicit registry of code-declared schedules."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, overload
from zoneinfo import ZoneInfo

from goatbeat.core.durations import parse_duration
from goatbeat.core.errors import ConfigurationError, NaiveDatetimeError
from goatbeat.core.misfire import DEFAULT_GRACE, DEFAULT_MAX_CATCH_UP, MisfirePolicy, MisfireRules
from goatbeat.core.schedule import Routing, ScheduleDefinition
from goatbeat.core.tasks import TaskCall, task_path
from goatbeat.core.time import Instant, resolve_timezone
from goatbeat.core.triggers import CronTrigger, IntervalTrigger, Trigger

# Anchoring on the epoch keeps interval occurrences stable across restarts and deploys.
DEFAULT_INTERVAL_ANCHOR: Final = Instant.of(datetime(1970, 1, 1, tzinfo=UTC))

type TaskLike = Callable[[], object] | TaskCall
type MisfirePolicyName = MisfirePolicy | Literal["run_once", "skip", "catch_up"]


class Registry:
    def __init__(self, *, timezone: str | ZoneInfo = "UTC") -> None:
        self._timezone = resolve_timezone(timezone)
        self._definitions: dict[str, ScheduleDefinition] = {}

    @overload
    def schedule(
        self,
        *,
        name: str,
        task: TaskLike,
        cron: str,
        timezone: str | ZoneInfo | None = None,
        misfire_policy: MisfirePolicyName = MisfirePolicy.RUN_ONCE,
        misfire_grace: timedelta = DEFAULT_GRACE,
        max_catch_up: int = DEFAULT_MAX_CATCH_UP,
        queue: str | None = None,
        priority: int | None = None,
        backend: str | None = None,
        enabled: bool = True,
    ) -> ScheduleDefinition: ...
    @overload
    def schedule(
        self,
        *,
        name: str,
        task: TaskLike,
        every: str | timedelta,
        start_at: datetime | None = None,
        misfire_policy: MisfirePolicyName = MisfirePolicy.RUN_ONCE,
        misfire_grace: timedelta = DEFAULT_GRACE,
        max_catch_up: int = DEFAULT_MAX_CATCH_UP,
        queue: str | None = None,
        priority: int | None = None,
        backend: str | None = None,
        enabled: bool = True,
    ) -> ScheduleDefinition: ...
    def schedule(
        self,
        *,
        name: str,
        task: TaskLike,
        cron: str | None = None,
        timezone: str | ZoneInfo | None = None,
        every: str | timedelta | None = None,
        start_at: datetime | None = None,
        misfire_policy: MisfirePolicyName = MisfirePolicy.RUN_ONCE,
        misfire_grace: timedelta = DEFAULT_GRACE,
        max_catch_up: int = DEFAULT_MAX_CATCH_UP,
        queue: str | None = None,
        priority: int | None = None,
        backend: str | None = None,
        enabled: bool = True,
    ) -> ScheduleDefinition:
        if name in self._definitions:
            raise ConfigurationError(f"schedule {name!r} is already registered")
        definition = ScheduleDefinition(
            name=name,
            task=task if isinstance(task, TaskCall) else TaskCall(task_path(task)),
            trigger=self._trigger(cron, timezone, every, start_at),
            misfire=MisfireRules(MisfirePolicy(misfire_policy), misfire_grace, max_catch_up),
            routing=Routing(queue=queue, priority=priority, backend=backend),
            enabled=enabled,
        )
        self._definitions[name] = definition
        return definition

    def definitions(self) -> tuple[ScheduleDefinition, ...]:
        return tuple(self._definitions.values())

    def _trigger(
        self,
        cron: str | None,
        timezone: str | ZoneInfo | None,
        every: str | timedelta | None,
        start_at: datetime | None,
    ) -> Trigger:
        if cron is not None and every is None:
            return CronTrigger.parse(cron, timezone or self._timezone)
        if every is None or cron is not None:
            raise ConfigurationError("a schedule needs exactly one of cron= or every=")
        try:
            anchor = DEFAULT_INTERVAL_ANCHOR if start_at is None else Instant.of(start_at)
        except NaiveDatetimeError as error:
            raise ConfigurationError(str(error)) from error
        return IntervalTrigger(parse_duration(every), anchor)
