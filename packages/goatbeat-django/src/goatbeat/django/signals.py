"""Completion tracking: Django Tasks workers report back through ``task_finished``."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.db import DatabaseError
from django.tasks import TaskResultStatus

from goatbeat.core.errors import StoreUnavailableError
from goatbeat.core.observability import LOGGER_NAME, Event, log_event
from goatbeat.core.time import Instant
from goatbeat.django.conf import DjangoSettings
from goatbeat.django.provider import DjangoProvider
from goatbeat.postgres.store import PostgresStore

if TYPE_CHECKING:
    from django.tasks import TaskResult

logger = logging.getLogger(LOGGER_NAME)


def record_task_completion(
    sender: object, task_result: TaskResult[..., object], **kwargs: object
) -> None:
    del sender, kwargs
    if task_result.status not in (TaskResultStatus.SUCCESSFUL, TaskResultStatus.FAILED):
        return
    finished = task_result.finished_at or datetime.now(UTC)
    try:
        store = PostgresStore(DjangoProvider(DjangoSettings.from_django().database))
        store.record_completion(
            task_result.id,
            task_result.task.module_path,
            succeeded=task_result.status == TaskResultStatus.SUCCESSFUL,
            at=Instant.of(finished),
        )
    except (StoreUnavailableError, DatabaseError) as error:
        # Bookkeeping must never fail the task itself: the execution just stays "dispatched".
        log_event(logger, Event.STORE_UNAVAILABLE, logging.WARNING, error=str(error))
