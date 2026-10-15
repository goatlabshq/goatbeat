import logging
import threading
import time
import uuid
from datetime import timedelta
from typing import Final

from goatbeat.core.config import GoatbeatConfig
from goatbeat.core.errors import ConfigurationError, LeaseLostError
from goatbeat.core.execution import Execution, ExecutionStatus, Lease
from goatbeat.core.ids import IdempotencyKey
from goatbeat.core.lease_keeper import LeaseKeeper
from goatbeat.core.misfire import plan_occurrences
from goatbeat.core.observability import LOGGER_NAME, Event, MetricsSink, NoopMetrics, log_event
from goatbeat.core.protocols import LeaseManager, ScheduleStore, TaskSubmitter
from goatbeat.core.registry import SupportsDefinitions
from goatbeat.core.schedule import Schedule
from goatbeat.core.submission import PendingSubmission
from goatbeat.core.time import Clock, Instant, SystemClock

RETRY_BASE: Final = timedelta(seconds=5)
RETRY_CAP: Final = timedelta(minutes=5)
ERROR_BACKOFF_BASE: Final = timedelta(seconds=1)
ERROR_BACKOFF_CAP: Final = timedelta(seconds=30)
STOP_CHECK: Final = timedelta(seconds=1)


def retry_delay(retry_count: int) -> timedelta:
    return min(RETRY_BASE * 2 ** (retry_count - 1), RETRY_CAP)


class Scheduler:
    def __init__(
        self,
        *,
        store: ScheduleStore,
        leases: LeaseManager,
        submitter: TaskSubmitter,
        config: GoatbeatConfig,
        registry: SupportsDefinitions | None = None,
        clock: Clock | None = None,
        metrics: MetricsSink | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._store = store
        self._submitter = submitter
        self._config = config
        self._registry = registry
        self._clock = clock or SystemClock()
        self._metrics = metrics or NoopMetrics()
        self._logger = logger or logging.getLogger(LOGGER_NAME)
        self._keeper = LeaseKeeper(
            leases,
            config.scheduler_id,
            ttl=config.lease_ttl,
            renew_interval=config.lease_renew_interval,
            clock=self._clock,
            metrics=self._metrics,
            logger=self._logger,
        )

    @property
    def is_leader(self) -> bool:
        return self._keeper.valid()

    def start(self) -> None:
        """Publish code-declared schedules; safe to call from every instance."""
        if self._registry is not None:
            self._store.sync_code_schedules(self._registry.definitions(), self._clock.now())

    def tick(self) -> Instant:
        started = time.perf_counter()
        lease = self._keeper.ensure()
        if lease is not None:
            self._resubmit_pending(lease)
            self._dispatch_due(lease)
        self._metrics.tick_duration(time.perf_counter() - started)
        return self._next_wakeup()

    def run(self, stop: threading.Event) -> None:
        log_event(
            self._logger, Event.SCHEDULER_STARTED, scheduler_id=self._config.scheduler_id.value
        )
        failures = 0
        started = False
        try:
            while not stop.is_set():
                try:
                    if not started:
                        self.start()
                        started = True
                    wake = self.tick()
                    failures = 0
                except Exception as error:
                    failures += 1
                    log_event(
                        self._logger,
                        Event.TICK_FAILED,
                        logging.ERROR,
                        exc_info=True,
                        error=str(error),
                    )
                    wake = self._clock.now() + min(
                        ERROR_BACKOFF_BASE * 2 ** (failures - 1), ERROR_BACKOFF_CAP
                    )
                self.sleep_until(wake, stop)
        finally:
            self._keeper.release()
            log_event(
                self._logger, Event.SCHEDULER_STOPPED, scheduler_id=self._config.scheduler_id.value
            )

    def release(self) -> None:
        self._keeper.release()

    def run_now(self, name: str) -> Execution:
        """Request an extra run; whichever instance leads dispatches it on its next tick."""
        schedule = self._store.get_schedule(name)
        if schedule is None:
            raise ConfigurationError(f"unknown schedule {name!r}")
        key = IdempotencyKey(f"manual:{uuid.uuid4().hex}")
        return self._store.request_run(schedule, key, self._config.scheduler_id, self._clock.now())

    def _resubmit_pending(self, lease: Lease) -> None:
        del lease  # submissions are recorded unfenced: the idempotency key protects them
        now = self._clock.now()
        pending = self._store.pending_submissions(
            now, stale_before=now - self._config.lease_ttl, limit=self._config.batch_size
        )
        for item in pending:
            if not self._keeper.valid():
                return
            self._submit(item)

    def _dispatch_due(self, lease: Lease) -> None:
        while self._keeper.valid():
            now = self._clock.now()
            due = self._store.due_schedules(now, self._config.batch_size)
            for schedule in due:
                if not self._keeper.valid() or not self._claim_and_submit(lease, schedule, now):
                    return
            if len(due) < self._config.batch_size:
                return

    def _claim_and_submit(self, lease: Lease, schedule: Schedule, now: Instant) -> bool:
        definition = schedule.definition
        try:
            plan = plan_occurrences(
                definition.trigger, schedule.next_run_at, now, definition.misfire
            )
        except Exception as error:
            log_event(
                self._logger,
                Event.SCHEDULE_FAILED,
                logging.ERROR,
                exc_info=True,
                schedule=schedule.name,
                error=str(error),
            )
            return True
        try:
            executions = self._store.claim(lease, schedule, plan, now)
        except LeaseLostError:
            self._keeper.lost()
            return False
        for execution in executions:
            if execution.status is ExecutionStatus.SKIPPED:
                self._metrics.occurrences(ExecutionStatus.SKIPPED, execution.missed_count + 1)
                log_event(
                    self._logger,
                    Event.OCCURRENCE_SKIPPED,
                    schedule=schedule.name,
                    scheduled_at=execution.scheduled_at.isoformat(),
                    missed_count=execution.missed_count,
                )
                continue
            self._metrics.occurrences(ExecutionStatus.CLAIMED)
            if execution.missed_count:
                self._metrics.occurrences(ExecutionStatus.SKIPPED, execution.missed_count)
            self._submit(PendingSubmission(execution, schedule))
        return True

    def _submit(self, pending: PendingSubmission) -> None:
        if not self._keeper.valid():
            return  # stays claimed; the next leader resubmits it with the same key
        execution = pending.execution
        submission = pending.to_submission()
        try:
            receipt = self._submitter.submit(submission)
        except Exception as error:
            self._record_failure(execution, error)
            return
        now = self._clock.now()
        self._store.mark_dispatched(execution.idempotency_key, now, receipt)
        self._metrics.occurrences(receipt.status)
        self._metrics.dispatch_latency((now - execution.scheduled_at).total_seconds())
        log_event(
            self._logger,
            Event.OCCURRENCE_DISPATCHED,
            schedule=submission.schedule_name,
            idempotency_key=execution.idempotency_key.value,
            scheduled_at=execution.scheduled_at.isoformat(),
            result_id=receipt.result_id,
        )

    def _record_failure(self, execution: Execution, error: Exception) -> None:
        retry_count = execution.retry_count + 1
        final = retry_count > self._config.max_submit_retries
        retry_at = None if final else self._clock.now() + retry_delay(retry_count)
        self._store.mark_submit_failed(execution.idempotency_key, str(error), retry_at)
        self._metrics.occurrences(
            ExecutionStatus.FAILED if final else ExecutionStatus.SUBMIT_FAILED
        )
        log_event(
            self._logger,
            Event.SUBMISSION_FAILED,
            logging.ERROR if final else logging.WARNING,
            idempotency_key=execution.idempotency_key.value,
            retry_count=retry_count,
            final=final,
            error=str(error),
        )

    def _next_wakeup(self) -> Instant:
        now = self._clock.now()
        candidates = [
            now + self._config.max_sleep,
            now + timedelta(seconds=self._keeper.seconds_until_renewal()),
        ]
        if self._keeper.valid():
            upcoming = self._store.next_wakeup()
            if upcoming is not None:
                candidates.append(max(upcoming, now))
        return min(candidates)

    def sleep_until(self, wake: Instant, stop: threading.Event) -> None:
        """Converted to a monotonic deadline once, so wall clock steps cannot stretch the sleep."""
        deadline = self._clock.monotonic() + (wake - self._clock.now()).total_seconds()
        while not stop.is_set():
            remaining = deadline - self._clock.monotonic()
            if remaining <= 0:
                return
            timeout = min(timedelta(seconds=remaining), STOP_CHECK)
            if self._store.wait_for_change(timeout):
                return
