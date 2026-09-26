"""Tables owned by Django migrations; they must match ``goatbeat.postgres.schema`` exactly."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from django.db import models
from django.db.models.functions import Now

if TYPE_CHECKING:
    from datetime import datetime

    from goatbeat.core.json import JsonValue

    # django-stubs fields need their value types spelled out for pyright (mypy infers them).
    type Text = models.TextField[str, str]
    type OptionalText = models.TextField[str | None, str | None]
    type BigInteger = models.BigIntegerField[int, int]
    type OptionalBigInteger = models.BigIntegerField[int | None, int | None]
    type Integer = models.IntegerField[int, int]
    type OptionalInteger = models.IntegerField[int | None, int | None]
    type Boolean = models.BooleanField[bool, bool]
    type Moment = models.DateTimeField[datetime, datetime]
    type OptionalMoment = models.DateTimeField[datetime | None, datetime | None]
    type Json = models.JSONField[JsonValue, JsonValue]
    type AutoId = models.BigAutoField[int, int]


class Schedule(models.Model):
    id: Text = models.TextField(primary_key=True)
    name: Text = models.TextField(unique=True)
    source: Text = models.TextField()
    task_path: Text = models.TextField()
    task_args: Json = models.JSONField()
    task_kwargs: Json = models.JSONField()
    trigger_kind: Text = models.TextField()
    interval_us: OptionalBigInteger = models.BigIntegerField(null=True)
    start_at: OptionalMoment = models.DateTimeField(null=True)
    cron: OptionalText = models.TextField(null=True)
    timezone: OptionalText = models.TextField(null=True)
    misfire_policy: Text = models.TextField()
    misfire_grace_us: BigInteger = models.BigIntegerField()
    max_catch_up: Integer = models.IntegerField()
    queue: OptionalText = models.TextField(null=True)
    priority: OptionalInteger = models.IntegerField(null=True)
    backend: OptionalText = models.TextField(null=True)
    enabled: Boolean = models.BooleanField()
    next_run_at: Moment = models.DateTimeField()
    created_at: Moment = models.DateTimeField(db_default=Now())
    updated_at: Moment = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "goatbeat_schedule"
        ordering = ("name",)
        indexes = (
            models.Index(
                fields=["next_run_at"],
                condition=models.Q(enabled=True),
                name="goatbeat_schedule_due",
            ),
        )

    @override
    def __str__(self) -> str:
        return self.name


class Execution(models.Model):
    id: AutoId = models.BigAutoField(primary_key=True)
    schedule: models.ForeignKey[Schedule, Schedule] = models.ForeignKey(
        Schedule, on_delete=models.DB_CASCADE, db_index=False, related_name="executions"
    )
    scheduled_at: Moment = models.DateTimeField()
    idempotency_key: Text = models.TextField(unique=True)
    status: Text = models.TextField()
    scheduler_id: Text = models.TextField()
    fencing_token: BigInteger = models.BigIntegerField()
    claimed_at: Moment = models.DateTimeField()
    missed_count: Integer = models.IntegerField()
    retry_count: Integer = models.IntegerField()
    dispatched_at: OptionalMoment = models.DateTimeField(null=True)
    completed_at: OptionalMoment = models.DateTimeField(null=True)
    next_retry_at: OptionalMoment = models.DateTimeField(null=True)
    backend_result_id: OptionalText = models.TextField(null=True)
    error: OptionalText = models.TextField(null=True)

    class Meta:
        db_table = "goatbeat_execution"
        ordering = ("-scheduled_at",)
        indexes = (
            models.Index(fields=["schedule", "-scheduled_at"], name="goatbeat_execution_history"),
            models.Index(
                fields=["next_retry_at"],
                condition=models.Q(status="submit_failed"),
                name="goatbeat_execution_retry",
            ),
            models.Index(
                fields=["claimed_at"],
                condition=models.Q(status="requested"),
                name="goatbeat_execution_requested",
            ),
            models.Index(
                fields=["claimed_at"],
                condition=models.Q(status="claimed"),
                name="goatbeat_execution_claimed",
            ),
            models.Index(
                fields=["backend_result_id"],
                condition=models.Q(backend_result_id__isnull=False),
                name="goatbeat_execution_result",
            ),
        )

    @override
    def __str__(self) -> str:
        return self.idempotency_key


class Lease(models.Model):
    partition: Integer = models.IntegerField(primary_key=True)
    holder_id: OptionalText = models.TextField(null=True)
    fencing_token: BigInteger = models.BigIntegerField()
    expires_at: Moment = models.DateTimeField()

    class Meta:
        db_table = "goatbeat_lease"
