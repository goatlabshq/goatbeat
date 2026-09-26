"""Admin form: every value is validated by the core types, the same as code declarations."""

from datetime import timedelta
from typing import Any, Final, override

from django import forms
from django.core.exceptions import ValidationError
from django.tasks import Task
from django.utils.module_loading import import_string

from goatbeat.core.durations import parse_duration
from goatbeat.core.errors import ConfigurationError, NaiveDatetimeError
from goatbeat.core.json import ensure_json
from goatbeat.core.misfire import DEFAULT_GRACE, MisfirePolicy, MisfireRules
from goatbeat.core.registry import DEFAULT_INTERVAL_ANCHOR
from goatbeat.core.schedule import Routing, ScheduleDefinition
from goatbeat.core.tasks import TaskCall
from goatbeat.core.triggers import CronTrigger, IntervalTrigger, Trigger
from goatbeat.django.conf import DjangoSettings
from goatbeat.django.generics import ScheduleModelForm
from goatbeat.django.models import Schedule

CRON: Final = "cron"
INTERVAL: Final = "interval"
MICROSECONDS_PER_SECOND: Final = 1_000_000


class ScheduleForm(ScheduleModelForm):
    trigger_kind = forms.ChoiceField(choices=[(CRON, "Cron"), (INTERVAL, "Interval")])
    cron = forms.CharField(required=False, help_text="Five fields, for example 0 9 * * 1-5.")
    timezone = forms.CharField(required=False, help_text="Defaults to the Goatbeat timezone.")
    every = forms.CharField(required=False, help_text="30s, 5m, 1h or 1d.")
    task_args = forms.JSONField(required=False, initial=list, help_text="A JSON array.")
    task_kwargs = forms.JSONField(required=False, initial=dict, help_text="A JSON object.")
    misfire_policy = forms.ChoiceField(
        choices=[(policy.value, policy.value) for policy in MisfirePolicy]
    )
    misfire_grace_seconds = forms.IntegerField(
        min_value=0, initial=int(DEFAULT_GRACE.total_seconds())
    )
    queue = forms.CharField(required=False)
    priority = forms.IntegerField(required=False)
    backend = forms.CharField(required=False)
    definition: ScheduleDefinition

    class Meta:
        model = Schedule
        fields = ("name", "task_path", "max_catch_up", "enabled")

    # Any: ModelForm.__init__ and clean() are typed that way by django-stubs.
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        schedule = self.instance
        if schedule.pk:
            self.initial.update(
                {
                    "trigger_kind": schedule.trigger_kind,
                    "cron": schedule.cron or "",
                    "timezone": schedule.timezone or "",
                    "every": _seconds_text(schedule.interval_us),
                    "task_args": schedule.task_args,
                    "task_kwargs": schedule.task_kwargs,
                    "misfire_policy": schedule.misfire_policy,
                    "misfire_grace_seconds": schedule.misfire_grace_us // MICROSECONDS_PER_SECOND,
                    "queue": schedule.queue or "",
                    "priority": schedule.priority,
                    "backend": schedule.backend or "",
                }
            )

    @override
    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        if self.errors:
            return cleaned
        if self.instance.pk:
            # The admin shows the name read-only on edit, so it is not posted back.
            cleaned.setdefault("name", self.instance.name)
        try:
            self.definition = definition_from(cleaned)
        except (ConfigurationError, NaiveDatetimeError, ValueError) as error:
            raise ValidationError(str(error)) from error
        return cleaned


def definition_from(cleaned: dict[str, Any]) -> ScheduleDefinition:
    path = str(cleaned["task_path"])
    _ensure_django_task(path)
    args = ensure_json(cleaned.get("task_args") or [])
    kwargs = ensure_json(cleaned.get("task_kwargs") or {})
    if not isinstance(args, list) or not isinstance(kwargs, dict):
        raise ConfigurationError("task arguments must be a JSON array and a JSON object")
    return ScheduleDefinition(
        name=str(cleaned["name"]),
        task=TaskCall(path, tuple(args), kwargs),
        trigger=_trigger(cleaned),
        misfire=MisfireRules(
            MisfirePolicy(cleaned["misfire_policy"]),
            timedelta(seconds=int(cleaned["misfire_grace_seconds"])),
            int(cleaned["max_catch_up"]),
        ),
        routing=Routing(
            queue=cleaned.get("queue") or None,
            priority=cleaned.get("priority"),
            backend=cleaned.get("backend") or None,
        ),
        enabled=bool(cleaned.get("enabled")),
    )


def _trigger(cleaned: dict[str, Any]) -> Trigger:
    if cleaned["trigger_kind"] == CRON:
        timezone = cleaned.get("timezone") or DjangoSettings.from_django().config.timezone
        return CronTrigger.parse(str(cleaned.get("cron") or ""), timezone)
    return IntervalTrigger(parse_duration(str(cleaned.get("every") or "")), DEFAULT_INTERVAL_ANCHOR)


def _ensure_django_task(path: str) -> None:
    try:
        target: object = import_string(path)
    except ImportError as error:
        raise ConfigurationError(f"no Django task at {path!r}") from error
    if not isinstance(target, Task):
        raise ConfigurationError(f"{path!r} is not a django.tasks.Task")


def _seconds_text(interval_us: int | None) -> str:
    return "" if interval_us is None else f"{interval_us // MICROSECONDS_PER_SECOND}s"
