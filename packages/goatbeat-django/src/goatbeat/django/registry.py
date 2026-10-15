from __future__ import annotations

from typing import TYPE_CHECKING, overload

from goatbeat.core.errors import ConfigurationError
from goatbeat.core.json import ensure_json
from goatbeat.core.misfire import DEFAULT_GRACE, DEFAULT_MAX_CATCH_UP, MisfirePolicy
from goatbeat.core.registry import MisfirePolicyName, Registry
from goatbeat.core.tasks import TaskCall

if TYPE_CHECKING:
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from django.tasks import Task

    from goatbeat.core.schedule import ScheduleDefinition


def call[**P, R](task: Task[P, R], /, *args: P.args, **kwargs: P.kwargs) -> TaskCall:
    return TaskCall(
        path=task.module_path,
        args=tuple(ensure_json(value) for value in args),
        kwargs={name: ensure_json(value) for name, value in kwargs.items()},
    )


class DjangoRegistry:
    def __init__(self, *, timezone: str | ZoneInfo = "UTC") -> None:
        self._registry = Registry(timezone=timezone)

    @overload
    def schedule[R](
        self,
        *,
        name: str,
        task: Task[[], R] | TaskCall,
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
    def schedule[R](
        self,
        *,
        name: str,
        task: Task[[], R] | TaskCall,
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
    def schedule[R](
        self,
        *,
        name: str,
        task: Task[[], R] | TaskCall,
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
        bound = task if isinstance(task, TaskCall) else TaskCall(task.module_path)
        if cron is not None and every is None:
            return self._registry.schedule(
                name=name,
                task=bound,
                cron=cron,
                timezone=timezone,
                misfire_policy=misfire_policy,
                misfire_grace=misfire_grace,
                max_catch_up=max_catch_up,
                queue=queue,
                priority=priority,
                backend=backend,
                enabled=enabled,
            )
        if every is None or cron is not None:
            raise ConfigurationError("a schedule needs exactly one of cron= or every=")
        return self._registry.schedule(
            name=name,
            task=bound,
            every=every,
            start_at=start_at,
            misfire_policy=misfire_policy,
            misfire_grace=misfire_grace,
            max_catch_up=max_catch_up,
            queue=queue,
            priority=priority,
            backend=backend,
            enabled=enabled,
        )

    def definitions(self) -> tuple[ScheduleDefinition, ...]:
        return self._registry.definitions()
