import threading
import time
from collections.abc import Sequence
from datetime import timedelta

import pytest
from sample_tasks import generate_report

from goatbeat.core import scheduler as scheduler_module
from goatbeat.core.config import GoatbeatConfig
from goatbeat.core.errors import (
    InvalidCronExpressionError,
    StoreUnavailableError,
    SubmissionError,
)
from goatbeat.core.execution import ExecutionStatus, Lease, SubmissionReceipt
from goatbeat.core.ids import SchedulerId
from goatbeat.core.misfire import MisfireRules, OccurrencePlan
from goatbeat.core.registry import DEFAULT_INTERVAL_ANCHOR, Registry
from goatbeat.core.scheduler import Scheduler
from goatbeat.core.stores.memory import MemoryStore
from goatbeat.core.submission import TaskSubmission
from goatbeat.core.testing import FakeClock
from goatbeat.core.testing.clock import DEFAULT_START
from goatbeat.core.time import Instant, SystemClock
from goatbeat.core.triggers import IntervalTrigger, Trigger

MINUTE = timedelta(minutes=1)
TTL = timedelta(seconds=30)
START = DEFAULT_START.datetime


class Crash(BaseException):
    """Simulates the process dying in the middle of a tick."""


class RecordingSubmitter:
    def __init__(self, *, failures: int = 0, crash: bool = False) -> None:
        self.submissions: list[TaskSubmission] = []
        self.attempts = 0
        self._failures = failures
        self._crash = crash

    def submit(self, submission: TaskSubmission) -> SubmissionReceipt:
        self.attempts += 1
        if self._crash:
            raise Crash
        if self._failures:
            self._failures -= 1
            raise SubmissionError("broker down")
        self.submissions.append(submission)
        return SubmissionReceipt(f"result-{len(self.submissions)}")


class UnavailableLeases:
    def acquire(self, holder: SchedulerId, ttl: timedelta) -> Lease | None:
        del holder, ttl
        raise StoreUnavailableError("connection refused")

    def release(self, lease: Lease) -> None:
        del lease
        raise StoreUnavailableError("connection refused")


def every_minute_registry(*, misfire_policy: str = "run_once") -> Registry:
    registry = Registry()
    registry.schedule(
        name="job",
        task=generate_report,
        every="1m",
        misfire_policy="skip" if misfire_policy == "skip" else "run_once",
    )
    return registry


def make_scheduler(
    store: MemoryStore,
    clock: FakeClock,
    submitter: RecordingSubmitter,
    name: str = "alice",
    *,
    registry: Registry | None = None,
    max_submit_retries: int = 5,
) -> Scheduler:
    config = GoatbeatConfig(
        scheduler_id=SchedulerId(name), lease_ttl=TTL, max_submit_retries=max_submit_retries
    )
    scheduler = Scheduler(
        store=store,
        leases=store,
        submitter=submitter,
        config=config,
        registry=registry or every_minute_registry(),
        clock=clock,
    )
    scheduler.start()
    return scheduler


def keys(submissions: Sequence[TaskSubmission]) -> list[str]:
    return [submission.idempotency_key.value for submission in submissions]


def test_due_occurrence_is_dispatched_once() -> None:
    clock = FakeClock()
    store = MemoryStore(clock)
    submitter = RecordingSubmitter()
    scheduler = make_scheduler(store, clock, submitter)
    scheduler.tick()
    assert submitter.submissions == []
    clock.advance(MINUTE)
    scheduler.tick()
    scheduler.tick()
    [submission] = submitter.submissions
    assert submission.task.path == "sample_tasks.generate_report"
    assert submission.scheduled_at == clock.now()
    [execution] = store.recent_executions(None, limit=10)
    assert execution.status is ExecutionStatus.DISPATCHED
    assert execution.backend_result_id == "result-1"


def test_two_schedulers_never_dispatch_the_same_occurrence() -> None:
    clock = FakeClock()
    store = MemoryStore(clock)
    first, second = RecordingSubmitter(), RecordingSubmitter()
    alice = make_scheduler(store, clock, first, "alice")
    bob = make_scheduler(store, clock, second, "bob")
    for _ in range(10):
        clock.advance(MINUTE)
        bob.tick()
        alice.tick()
    dispatched = keys(first.submissions) + keys(second.submissions)
    assert len(dispatched) == 10
    assert len(set(dispatched)) == 10
    assert first.submissions == [] or second.submissions == []


def test_standby_takes_over_after_the_leader_dies() -> None:
    clock = FakeClock()
    store = MemoryStore(clock)
    first, second = RecordingSubmitter(), RecordingSubmitter()
    alice = make_scheduler(store, clock, first, "alice")
    bob = make_scheduler(store, clock, second, "bob")
    clock.advance(MINUTE)
    alice.tick()
    bob.tick()
    assert len(first.submissions) == 1
    for _ in range(3):  # alice is dead: only bob ticks from now on
        clock.advance(MINUTE)
        bob.tick()
    assert len(second.submissions) >= 2
    dispatched = keys(first.submissions) + keys(second.submissions)
    assert len(dispatched) == len(set(dispatched)) == 4


def test_a_claim_orphaned_by_a_crash_is_resubmitted_with_the_same_key() -> None:
    clock = FakeClock()
    store = MemoryStore(clock)
    crashing, healthy = RecordingSubmitter(crash=True), RecordingSubmitter()
    alice = make_scheduler(store, clock, crashing, "alice")
    bob = make_scheduler(store, clock, healthy, "bob")
    clock.advance(MINUTE)
    with pytest.raises(Crash):
        alice.tick()
    [orphan] = store.recent_executions(None, limit=1)
    assert orphan.status is ExecutionStatus.CLAIMED
    clock.advance(TTL + timedelta(seconds=1))
    bob.tick()
    assert orphan.idempotency_key in {s.idempotency_key for s in healthy.submissions}
    [recovered] = [
        e
        for e in store.recent_executions(None, limit=10)
        if e.idempotency_key == orphan.idempotency_key
    ]
    assert recovered.status is ExecutionStatus.DISPATCHED


def test_failed_submissions_are_retried_with_backoff_then_marked_failed() -> None:
    clock = FakeClock()
    store = MemoryStore(clock)
    submitter = RecordingSubmitter(failures=10)
    scheduler = make_scheduler(store, clock, submitter, max_submit_retries=2)
    clock.advance(MINUTE)
    scheduler.tick()
    [first] = store.recent_executions(None, limit=1)
    assert first.status is ExecutionStatus.SUBMIT_FAILED
    assert first.next_retry_at == clock.now() + timedelta(seconds=5)
    clock.advance(timedelta(seconds=5))
    scheduler.tick()
    [second] = [e for e in store.recent_executions(None, limit=10) if e.retry_count == 2]
    assert second.next_retry_at == clock.now() + timedelta(seconds=10)
    clock.advance(timedelta(seconds=10))
    scheduler.tick()
    [final] = [e for e in store.recent_executions(None, limit=10) if e.retry_count == 3]
    assert final.status is ExecutionStatus.FAILED
    assert final.error == "broker down"
    assert submitter.attempts == 3


def test_a_scheduler_that_lost_its_lease_stops_dispatching() -> None:
    clock = FakeClock()
    store = MemoryStore(clock)
    first, second = RecordingSubmitter(), RecordingSubmitter()
    alice = make_scheduler(store, clock, first, "alice")
    alice.tick()
    clock.advance(TTL + timedelta(seconds=1))
    bob = make_scheduler(store, clock, second, "bob")
    for _ in range(6):  # bob renews every 10 s, alice is paused (GC pause, frozen VM, ...)
        bob.tick()
        clock.advance(timedelta(seconds=10))
    alice.tick()
    assert first.submissions == []
    assert len(second.submissions) == 1


def test_tick_returns_the_earliest_useful_wakeup() -> None:
    clock = FakeClock()
    store = MemoryStore(clock)
    scheduler = make_scheduler(store, clock, RecordingSubmitter())
    assert scheduler.tick() == clock.now() + timedelta(seconds=10)  # lease renewal
    registry = Registry()
    registry.schedule(name="soon", task=generate_report, every="5s")
    soon = make_scheduler(MemoryStore(clock), clock, RecordingSubmitter(), registry=registry)
    assert soon.tick() == clock.now() + timedelta(seconds=5)


def test_skipped_occurrences_are_recorded_but_not_submitted() -> None:
    clock = FakeClock()
    store = MemoryStore(clock)
    submitter = RecordingSubmitter()
    scheduler = make_scheduler(
        store, clock, submitter, registry=every_minute_registry(misfire_policy="skip")
    )
    clock.advance(10 * MINUTE + timedelta(seconds=30))
    scheduler.tick()
    statuses = sorted(e.status for e in store.recent_executions(None, limit=10))
    assert statuses == [ExecutionStatus.DISPATCHED, ExecutionStatus.SKIPPED]
    assert len(submitter.submissions) == 1


def test_run_now_dispatches_a_manual_occurrence() -> None:
    clock = FakeClock()
    store = MemoryStore(clock)
    submitter = RecordingSubmitter()
    scheduler = make_scheduler(store, clock, submitter)
    scheduler.tick()
    execution = scheduler.run_now("job")
    assert execution.idempotency_key.value.startswith("manual:")
    assert keys(submitter.submissions) == [execution.idempotency_key.value]


def test_an_unavailable_store_does_not_crash_the_tick() -> None:
    clock = FakeClock()
    store = MemoryStore(clock)
    submitter = RecordingSubmitter()
    scheduler = Scheduler(
        store=store,
        leases=UnavailableLeases(),
        submitter=submitter,
        config=GoatbeatConfig(scheduler_id=SchedulerId("alice")),
        registry=every_minute_registry(),
        clock=clock,
    )
    scheduler.start()
    clock.advance(MINUTE)
    wake = scheduler.tick()
    assert submitter.submissions == []
    assert wake > clock.now()


def test_run_loop_dispatches_on_the_system_clock_and_stops_promptly() -> None:
    clock = SystemClock()
    store = MemoryStore(clock)
    submitter = RecordingSubmitter()
    registry = Registry()
    registry.schedule(name="fast", task=generate_report, every="1s")
    scheduler = Scheduler(
        store=store,
        leases=store,
        submitter=submitter,
        config=GoatbeatConfig(scheduler_id=SchedulerId("alice")),
        registry=registry,
        clock=clock,
    )
    stop = threading.Event()
    thread = threading.Thread(target=scheduler.run, args=(stop,))
    thread.start()
    time.sleep(2.5)
    stop.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert len(submitter.submissions) >= 2
    assert store.acquire(SchedulerId("bob"), TTL) is not None  # the lease was released


class SlowSubmitter(RecordingSubmitter):
    """Each submission takes 25 s of (fake) time, longer than the local lease validity."""

    def __init__(self, clock: FakeClock) -> None:
        super().__init__()
        self._clock = clock

    def submit(self, submission: TaskSubmission) -> SubmissionReceipt:
        self._clock.advance(timedelta(seconds=25))
        return super().submit(submission)


def test_a_slow_tick_stops_before_the_local_lease_deadline() -> None:
    clock = FakeClock()
    store = MemoryStore(clock)
    submitter = SlowSubmitter(clock)
    registry = Registry()
    registry.schedule(name="a", task=generate_report, every="1m")
    registry.schedule(name="b", task=generate_report, every="1m")
    scheduler = make_scheduler(store, clock, submitter, registry=registry)
    clock.advance(MINUTE)
    scheduler.tick()
    assert len(submitter.submissions) == 1
    assert not scheduler.is_leader


def test_a_schedule_that_fails_to_plan_does_not_block_the_others(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    clock = FakeClock()
    store = MemoryStore(clock)
    submitter = RecordingSubmitter()
    registry = Registry()
    registry.schedule(name="broken", task=generate_report, every="1m")
    # Same grid, different anchor, so the two triggers compare unequal.
    registry.schedule(name="healthy", task=generate_report, every="1m", start_at=START)
    original = scheduler_module.plan_occurrences

    def plan(
        trigger: Trigger, next_run_at: Instant, now: Instant, rules: MisfireRules
    ) -> OccurrencePlan:
        if trigger == IntervalTrigger(MINUTE, DEFAULT_INTERVAL_ANCHOR):
            raise InvalidCronExpressionError("never matches")
        return original(trigger, next_run_at, now, rules)

    monkeypatch.setattr(scheduler_module, "plan_occurrences", plan)
    scheduler = make_scheduler(store, clock, submitter, registry=registry)
    clock.advance(MINUTE)
    scheduler.tick()
    assert [s.schedule_name for s in submitter.submissions] == ["healthy"]
    assert "schedule.failed" in caplog.text


class SteppingBackClock:
    """Wall time jumps back one hour once the sleep has started (NTP step, VM restore)."""

    def __init__(self) -> None:
        self._readings = 0

    def now(self) -> Instant:
        self._readings += 1
        offset = timedelta(0) if self._readings <= 2 else -timedelta(hours=1)
        return DEFAULT_START + offset

    def monotonic(self) -> float:
        return time.monotonic()


def test_a_backward_wall_clock_step_does_not_extend_the_sleep() -> None:
    clock = SteppingBackClock()
    store = MemoryStore(clock)
    scheduler = Scheduler(
        store=store,
        leases=store,
        submitter=RecordingSubmitter(),
        config=GoatbeatConfig(scheduler_id=SchedulerId("alice")),
        clock=clock,
    )
    stop = threading.Event()
    wake = clock.now() + timedelta(milliseconds=200)
    thread = threading.Thread(target=scheduler._sleep_until, args=(wake, stop))
    started = time.monotonic()
    thread.start()
    thread.join(timeout=3)
    stop.set()
    thread.join()
    assert time.monotonic() - started < 1
