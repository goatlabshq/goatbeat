"""Column mapping of schedule definitions, shared by every SQL store."""

import json
from datetime import timedelta
from typing import Final, TypedDict, cast

from goatbeat.core.errors import ConfigurationError
from goatbeat.core.json import JsonValue
from goatbeat.core.misfire import MisfirePolicy, MisfireRules
from goatbeat.core.schedule import Routing, ScheduleDefinition
from goatbeat.core.tasks import TaskCall
from goatbeat.core.time import Instant, resolve_timezone
from goatbeat.core.triggers import CronTrigger, IntervalTrigger, Trigger

INTERVAL: Final = "interval"
CRON: Final = "cron"


class DefinitionColumns(TypedDict):
    name: str
    task_path: str
    task_args: str
    task_kwargs: str
    trigger_kind: str
    interval: timedelta | None
    start_at: Instant | None
    cron: str | None
    timezone: str | None
    misfire_policy: str
    misfire_grace: timedelta
    max_catch_up: int
    queue: str | None
    priority: int | None
    backend: str | None
    enabled: bool


def definition_to_columns(definition: ScheduleDefinition) -> DefinitionColumns:
    trigger = definition.trigger
    interval = trigger if isinstance(trigger, IntervalTrigger) else None
    cron = trigger if isinstance(trigger, CronTrigger) else None
    return DefinitionColumns(
        name=definition.name,
        task_path=definition.task.path,
        task_args=json.dumps(list(definition.task.args), allow_nan=False),
        task_kwargs=json.dumps(dict(definition.task.kwargs), allow_nan=False),
        trigger_kind=INTERVAL if interval else CRON,
        interval=interval.every if interval else None,
        start_at=interval.start_at if interval else None,
        cron=cron.expression.text if cron else None,
        timezone=cron.timezone.key if cron else None,
        misfire_policy=definition.misfire.policy.value,
        misfire_grace=definition.misfire.grace,
        max_catch_up=definition.misfire.max_catch_up,
        queue=definition.routing.queue,
        priority=definition.routing.priority,
        backend=definition.routing.backend,
        enabled=definition.enabled,
    )


def definition_from_columns(columns: DefinitionColumns) -> ScheduleDefinition:
    return ScheduleDefinition(
        name=columns["name"],
        task=TaskCall(
            path=columns["task_path"],
            args=tuple(_decode_list(columns["task_args"])),
            kwargs=_decode_object(columns["task_kwargs"]),
        ),
        trigger=_trigger(columns),
        misfire=MisfireRules(
            MisfirePolicy(columns["misfire_policy"]),
            columns["misfire_grace"],
            columns["max_catch_up"],
        ),
        routing=Routing(
            queue=columns["queue"], priority=columns["priority"], backend=columns["backend"]
        ),
        enabled=columns["enabled"],
    )


def _trigger(columns: DefinitionColumns) -> Trigger:
    kind = columns["trigger_kind"]
    interval, start_at = columns["interval"], columns["start_at"]
    cron, timezone = columns["cron"], columns["timezone"]
    if kind == INTERVAL and interval is not None and start_at is not None:
        return IntervalTrigger(interval, start_at)
    if kind == CRON and cron is not None and timezone is not None:
        return CronTrigger.parse(cron, resolve_timezone(timezone))
    raise ConfigurationError(f"schedule {columns['name']!r} has an invalid trigger ({kind!r})")


def _decode_list(text: str) -> list[JsonValue]:
    value: object = json.loads(text)
    if not isinstance(value, list):
        raise ConfigurationError(f"task arguments must be a JSON array, got {text!r}")
    return cast("list[JsonValue]", value)


def _decode_object(text: str) -> dict[str, JsonValue]:
    value: object = json.loads(text)
    if not isinstance(value, dict):
        raise ConfigurationError(f"task keyword arguments must be a JSON object, got {text!r}")
    return cast("dict[str, JsonValue]", value)
