"""Admin for schedules and their execution history; writes go through the store."""

import uuid
from dataclasses import replace
from datetime import timedelta
from typing import Final, override

from django.contrib import admin
from django.db.models import OuterRef, QuerySet, Subquery
from django.http import HttpRequest

from goatbeat.core.ids import IdempotencyKey, SchedulerId
from goatbeat.core.schedule import ScheduleSource
from goatbeat.core.time import SystemClock
from goatbeat.django.generics import (
    ExecutionInline,
    ExecutionModelAdmin,
    ScheduleModelAdmin,
    ScheduleModelForm,
)
from goatbeat.django.models import Execution, Schedule
from goatbeat.django.runtime import store
from goatbeat.django.schedule_form import ScheduleForm

LAST_STATUS: Final = "last_status"
CODE_SCHEDULE_FIELDS: Final = ("name", "task_path", "trigger", "next_run_at", "enabled")
EDITABLE_FIELDS: Final = (
    "name",
    "task_path",
    "task_args",
    "task_kwargs",
    "trigger_kind",
    "cron",
    "timezone",
    "every",
    "misfire_policy",
    "misfire_grace_seconds",
    "max_catch_up",
    "queue",
    "priority",
    "backend",
    "enabled",
    "next_run_at",
)
CODE_SCHEDULE_READ_ONLY: Final = ("name", "task_path", "trigger", "next_run_at")


class EnabledOnlyForm(ScheduleModelForm):
    class Meta:
        model = Schedule
        fields = ("enabled",)


class RecentExecutionInline(ExecutionInline):
    model = Execution
    fields = ("scheduled_at", "status", "dispatched_at", "completed_at", "retry_count", "error")
    readonly_fields = fields
    ordering = ("-scheduled_at",)
    extra = 0
    max_num = 0
    can_delete = False
    show_change_link = True
    classes = ("collapse",)


@admin.register(Schedule)
class ScheduleAdmin(ScheduleModelAdmin):
    form = ScheduleForm
    list_display = ("name", "trigger", "source", "enabled", "next_run_at", LAST_STATUS)
    list_filter = ("source", "enabled", "trigger_kind")
    search_fields = ("name", "task_path")
    readonly_fields = ("next_run_at",)
    inlines = (RecentExecutionInline,)
    actions = ("enable_schedules", "disable_schedules", "run_schedules_now")

    @override
    def get_inlines(
        self, request: HttpRequest, obj: Schedule | None
    ) -> tuple[type[RecentExecutionInline], ...]:
        return (RecentExecutionInline,) if obj is not None else ()

    @override
    def get_queryset(self, request: HttpRequest) -> QuerySet[Schedule]:
        latest = Execution.objects.filter(schedule=OuterRef("pk")).order_by("-scheduled_at")
        return (
            super()
            .get_queryset(request)
            .annotate(**{LAST_STATUS: Subquery(latest.values("status")[:1])})
        )

    @override
    def get_fields(self, request: HttpRequest, obj: Schedule | None = None) -> tuple[str, ...]:
        return CODE_SCHEDULE_FIELDS if _is_code(obj) else EDITABLE_FIELDS

    @override
    def get_readonly_fields(
        self, request: HttpRequest, obj: Schedule | None = None
    ) -> tuple[str, ...]:
        if _is_code(obj):
            return CODE_SCHEDULE_READ_ONLY
        # Stores key schedules by name: renaming would silently create a second schedule.
        return ("name", "next_run_at") if obj is not None else ("next_run_at",)

    @override
    def get_form(
        self,
        request: HttpRequest,
        obj: Schedule | None = None,
        change: bool = False,
        **kwargs: object,
    ) -> type[ScheduleModelForm]:
        if _is_code(obj):
            kwargs["form"] = EnabledOnlyForm
        return super().get_form(request, obj, change, **kwargs)

    @override
    def save_model(
        self,
        request: HttpRequest,
        obj: Schedule,
        form: object,
        change: bool,
    ) -> None:
        now = SystemClock().now()
        backend = store()
        if _is_code(obj):
            backend.set_enabled(obj.name, enabled=obj.enabled, now=now)
            return
        if not isinstance(form, ScheduleForm):
            raise TypeError(f"unexpected form {type(form).__name__}")
        definition = form.definition
        existing = backend.get_schedule(obj.name) if change else None
        if existing is None:
            obj.pk = backend.save_schedule(definition, now).id.value
            return
        # Enabling goes through set_enabled so a long-disabled schedule restarts from now.
        backend.save_schedule(replace(definition, enabled=existing.definition.enabled), now)
        backend.set_enabled(obj.name, enabled=definition.enabled, now=now)

    @admin.display(description="trigger")
    def trigger(self, obj: Schedule) -> str:
        if obj.trigger_kind == "cron":
            return f"cron {obj.cron} ({obj.timezone})"
        interval = obj.interval_us or 0
        return f"every {_duration_text(interval)}"

    @admin.display(description="last status")
    def last_status(self, obj: Schedule) -> str:
        return str(getattr(obj, LAST_STATUS, None) or "")

    @admin.action(description="Enable selected schedules")
    def enable_schedules(self, request: HttpRequest, queryset: QuerySet[Schedule]) -> None:
        del request
        _set_enabled(queryset, enabled=True)

    @admin.action(description="Disable selected schedules")
    def disable_schedules(self, request: HttpRequest, queryset: QuerySet[Schedule]) -> None:
        del request
        _set_enabled(queryset, enabled=False)

    @admin.action(description="Run selected schedules now")
    def run_schedules_now(self, request: HttpRequest, queryset: QuerySet[Schedule]) -> None:
        backend = store()
        requester = SchedulerId(f"admin:{request.user.get_username()}")
        now = SystemClock().now()
        for name in queryset.values_list("name", flat=True):
            schedule = backend.get_schedule(name)
            if schedule is not None:
                key = IdempotencyKey(f"manual:{uuid.uuid4().hex}")
                backend.request_run(schedule, key, requester, now)


@admin.register(Execution)
class ExecutionAdmin(ExecutionModelAdmin):
    list_display = (
        "idempotency_key",
        "schedule",
        "status",
        "scheduled_at",
        "dispatched_at",
        "completed_at",
        "retry_count",
    )
    list_filter = ("status",)
    search_fields = ("idempotency_key", "schedule__name", "backend_result_id")
    list_select_related = ("schedule",)

    @override
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    @override
    def has_change_permission(self, request: HttpRequest, obj: Execution | None = None) -> bool:
        return False

    @override
    def has_delete_permission(self, request: HttpRequest, obj: Execution | None = None) -> bool:
        return False


def _is_code(obj: Schedule | None) -> bool:
    return obj is not None and obj.source == ScheduleSource.CODE.value


def _set_enabled(queryset: QuerySet[Schedule], *, enabled: bool) -> None:
    backend = store()
    now = SystemClock().now()
    for name in queryset.values_list("name", flat=True):
        backend.set_enabled(name, enabled=enabled, now=now)


def _duration_text(interval_us: int) -> str:
    return str(timedelta(microseconds=interval_us))
