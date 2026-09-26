"""Behavior every ScheduleStore and LeaseManager implementation must share.

Subclass ``StoreConformance`` in a ``Test*`` class and implement ``make_store``.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Final

from goatbeat.core.errors import ConfigurationError, LeaseLostError
from goatbeat.core.execution import ExecutionStatus, Lease, SubmissionReceipt
from goatbeat.core.ids import IdempotencyKey, SchedulerId
from goatbeat.core.misfire import Claim, OccurrencePlan
from goatbeat.core.protocols import LeaseManager, ScheduleStore
from goatbeat.core.schedule import Schedule, ScheduleDefinition, ScheduleSource
from goatbeat.core.tasks import TaskCall
from goatbeat.core.testing.clock import FakeClock
from goatbeat.core.time import Instant
from goatbeat.core.triggers import IntervalTrigger

TTL: Final = timedelta(seconds=30)
MINUTE: Final = timedelta(minutes=1)
ALICE: Final = SchedulerId("alice")
BOB: Final = SchedulerId("bob")
REQUESTER: Final = SchedulerId("admin:alice")


@dataclass(frozen=True, slots=True)
class StoreUnderTest:
    store: ScheduleStore
    leases: LeaseManager
    clock: FakeClock


def every_minute(name: str, clock: FakeClock, *, task: str = "tasks.run") -> ScheduleDefinition:
    return ScheduleDefinition(
        name=name, task=TaskCall(task), trigger=IntervalTrigger(MINUTE, clock.now())
    )


def one_claim(schedule: Schedule, at: Instant | None = None) -> OccurrencePlan:
    scheduled_at = at or schedule.next_run_at
    return OccurrencePlan((Claim(scheduled_at, ExecutionStatus.CLAIMED),), scheduled_at + MINUTE)


class StoreConformance(ABC):
    @abstractmethod
    def make_store(self, clock: FakeClock) -> StoreUnderTest: ...

    def _setup(self) -> StoreUnderTest:
        return self.make_store(FakeClock())

    def _leader(self, sut: StoreUnderTest, holder: SchedulerId = ALICE) -> Lease:
        lease = sut.leases.acquire(holder, TTL)
        assert lease is not None
        return lease

    def _saved(self, sut: StoreUnderTest, name: str = "job") -> Schedule:
        return sut.store.save_schedule(every_minute(name, sut.clock), sut.clock.now())

    # Leases

    def test_first_acquire_grants_a_lease(self) -> None:
        sut = self._setup()
        lease = self._leader(sut)
        assert lease.holder == ALICE

    def test_lease_is_exclusive_until_it_expires(self) -> None:
        sut = self._setup()
        self._leader(sut)
        assert sut.leases.acquire(BOB, TTL) is None
        sut.clock.advance(TTL - timedelta(seconds=1))
        assert sut.leases.acquire(BOB, TTL) is None

    def test_renewal_keeps_the_fencing_token(self) -> None:
        sut = self._setup()
        first = self._leader(sut)
        sut.clock.advance(timedelta(seconds=10))
        assert sut.leases.acquire(ALICE, TTL) == first

    def test_takeover_after_expiry_increments_the_fencing_token(self) -> None:
        sut = self._setup()
        first = self._leader(sut)
        sut.clock.advance(TTL + timedelta(seconds=1))
        second = self._leader(sut, BOB)
        assert second.holder == BOB
        assert second.token > first.token

    def test_release_lets_another_scheduler_take_over_immediately(self) -> None:
        sut = self._setup()
        first = self._leader(sut)
        sut.leases.release(first)
        assert self._leader(sut, BOB).token > first.token

    def test_release_of_a_lost_lease_does_nothing(self) -> None:
        sut = self._setup()
        first = self._leader(sut)
        sut.clock.advance(TTL + timedelta(seconds=1))
        second = self._leader(sut, BOB)
        sut.leases.release(first)
        assert sut.leases.acquire(ALICE, TTL) is None
        assert sut.leases.acquire(BOB, TTL) == second

    # Schedules

    def test_saved_schedule_starts_at_its_next_occurrence(self) -> None:
        sut = self._setup()
        schedule = self._saved(sut)
        assert schedule.source is ScheduleSource.STORE
        assert schedule.next_run_at == sut.clock.now() + MINUTE
        assert sut.store.get_schedule("job") == schedule

    def test_saving_an_existing_store_schedule_updates_it(self) -> None:
        sut = self._setup()
        first = self._saved(sut)
        updated = replace(first.definition, task=TaskCall("tasks.other"))
        second = sut.store.save_schedule(updated, sut.clock.now())
        assert second.id == first.id
        assert second.definition.task == TaskCall("tasks.other")

    def test_saving_over_a_code_schedule_is_rejected(self) -> None:
        sut = self._setup()
        sut.store.sync_code_schedules([every_minute("job", sut.clock)], sut.clock.now())
        try:
            self._saved(sut)
        except ConfigurationError:
            return
        raise AssertionError("a code-declared schedule must not be overwritten")

    def test_code_sync_inserts_then_keeps_the_grid_when_unchanged(self) -> None:
        sut = self._setup()
        definition = every_minute("job", sut.clock)
        sut.store.sync_code_schedules([definition], sut.clock.now())
        before = sut.store.get_schedule("job")
        assert before is not None
        assert before.source is ScheduleSource.CODE
        sut.clock.advance(5 * MINUTE)
        sut.store.sync_code_schedules([definition], sut.clock.now())
        assert sut.store.get_schedule("job") == before

    def test_code_sync_recomputes_next_run_when_the_trigger_changes(self) -> None:
        sut = self._setup()
        sut.store.sync_code_schedules([every_minute("job", sut.clock)], sut.clock.now())
        sut.clock.advance(5 * MINUTE)
        changed = replace(
            every_minute("job", sut.clock), trigger=IntervalTrigger(2 * MINUTE, sut.clock.now())
        )
        sut.store.sync_code_schedules([changed], sut.clock.now())
        after = sut.store.get_schedule("job")
        assert after is not None
        assert after.next_run_at == sut.clock.now() + 2 * MINUTE

    def test_code_sync_keeps_the_enabled_flag_set_by_an_operator(self) -> None:
        sut = self._setup()
        definition = every_minute("job", sut.clock)
        sut.store.sync_code_schedules([definition], sut.clock.now())
        sut.store.set_enabled("job", enabled=False, now=sut.clock.now())
        sut.store.sync_code_schedules([definition], sut.clock.now())
        schedule = sut.store.get_schedule("job")
        assert schedule is not None
        assert not schedule.definition.enabled

    def test_code_sync_prunes_only_when_asked(self) -> None:
        sut = self._setup()
        now = sut.clock.now()
        sut.store.sync_code_schedules([every_minute("a", sut.clock)], now)
        self._saved(sut, "from-admin")
        sut.store.sync_code_schedules([every_minute("b", sut.clock)], now)
        kept = sut.store.get_schedule("a")
        assert kept is not None
        assert kept.definition.enabled
        sut.store.sync_code_schedules([every_minute("b", sut.clock)], now, prune=True)
        pruned = sut.store.get_schedule("a")
        admin = sut.store.get_schedule("from-admin")
        assert pruned is not None
        assert not pruned.definition.enabled
        assert admin is not None
        assert admin.definition.enabled

    def test_list_schedules_is_sorted_by_name(self) -> None:
        sut = self._setup()
        for name in ("b", "c", "a"):
            self._saved(sut, name)
        assert [schedule.name for schedule in sut.store.list_schedules()] == ["a", "b", "c"]

    def test_reenabling_restarts_from_now(self) -> None:
        sut = self._setup()
        self._saved(sut)
        sut.store.set_enabled("job", enabled=False, now=sut.clock.now())
        sut.clock.advance(10 * MINUTE)
        sut.store.set_enabled("job", enabled=True, now=sut.clock.now())
        schedule = sut.store.get_schedule("job")
        assert schedule is not None
        assert schedule.next_run_at == sut.clock.now() + MINUTE

    def test_due_schedules_are_ordered_limited_and_enabled_only(self) -> None:
        sut = self._setup()
        for name in ("a", "b", "c"):
            self._saved(sut, name)
            sut.clock.advance(timedelta(seconds=1))
        sut.store.set_enabled("b", enabled=False, now=sut.clock.now())
        now = sut.clock.advance(2 * MINUTE)
        assert [s.name for s in sut.store.due_schedules(now, limit=10)] == ["a", "c"]
        assert [s.name for s in sut.store.due_schedules(now, limit=1)] == ["a"]
        assert sut.store.due_schedules(now - 2 * MINUTE, limit=10) == []

    # Claims

    def test_claim_records_executions_and_advances_the_schedule(self) -> None:
        sut = self._setup()
        schedule = self._saved(sut)
        now = sut.clock.advance(MINUTE)
        lease = self._leader(sut)
        [execution] = sut.store.claim(lease, schedule, one_claim(schedule), now)
        assert execution.status is ExecutionStatus.CLAIMED
        assert execution.scheduled_at == schedule.next_run_at
        assert execution.idempotency_key.value == (
            f"{schedule.id.value}:{schedule.next_run_at.isoformat()}"
        )
        assert execution.fencing_token == lease.token
        assert execution.scheduler_id == ALICE
        after = sut.store.get_schedule("job")
        assert after is not None
        assert after.next_run_at == schedule.next_run_at + MINUTE

    def test_duplicate_claim_of_an_occurrence_yields_nothing(self) -> None:
        sut = self._setup()
        schedule = self._saved(sut)
        now = sut.clock.advance(MINUTE)
        lease = self._leader(sut)
        sut.store.claim(lease, schedule, one_claim(schedule), now)
        assert sut.store.claim(lease, schedule, one_claim(schedule), now) == []
        assert len(sut.store.recent_executions(schedule.id, limit=10)) == 1

    def test_claim_with_a_stale_fencing_token_is_refused(self) -> None:
        sut = self._setup()
        schedule = self._saved(sut)
        stale = self._leader(sut)
        sut.clock.advance(TTL + timedelta(seconds=1))
        self._leader(sut, BOB)
        try:
            sut.store.claim(stale, schedule, one_claim(schedule), sut.clock.now())
        except LeaseLostError:
            assert sut.store.recent_executions(schedule.id, limit=10) == []
            return
        raise AssertionError("a stale leader must not claim")

    def test_claim_with_an_expired_lease_is_refused_even_without_takeover(self) -> None:
        sut = self._setup()
        schedule = self._saved(sut)
        lease = self._leader(sut)
        sut.clock.advance(TTL + timedelta(seconds=1))
        try:
            sut.store.claim(lease, schedule, one_claim(schedule), sut.clock.now())
        except LeaseLostError:
            return
        raise AssertionError("an expired lease must not claim")

    def test_claim_does_not_move_a_schedule_changed_concurrently(self) -> None:
        sut = self._setup()
        schedule = self._saved(sut)
        sut.store.set_enabled("job", enabled=False, now=sut.clock.now())
        now = sut.clock.advance(3 * MINUTE)
        sut.store.set_enabled("job", enabled=True, now=now)
        lease = self._leader(sut)
        sut.store.claim(lease, schedule, one_claim(schedule), now)
        after = sut.store.get_schedule("job")
        assert after is not None
        assert after.next_run_at == now + MINUTE

    def test_skipped_claims_are_recorded_with_their_missed_count(self) -> None:
        sut = self._setup()
        schedule = self._saved(sut)
        now = sut.clock.advance(MINUTE)
        lease = self._leader(sut)
        at = schedule.next_run_at
        plan = OccurrencePlan((Claim(at, ExecutionStatus.SKIPPED, 7),), at + MINUTE)
        [execution] = sut.store.claim(lease, schedule, plan, now)
        assert execution.status is ExecutionStatus.SKIPPED
        assert execution.missed_count == 7

    def test_a_requested_run_is_pending_immediately_without_a_lease(self) -> None:
        sut = self._setup()
        schedule = self._saved(sut)
        key = IdempotencyKey("manual:1234")
        execution = sut.store.request_run(schedule, key, REQUESTER, sut.clock.now())
        assert execution.idempotency_key == key
        assert execution.status is ExecutionStatus.REQUESTED
        assert execution.scheduler_id == REQUESTER
        now = sut.clock.now()
        [pending] = sut.store.pending_submissions(now, stale_before=now - TTL, limit=10)
        assert pending.execution.idempotency_key == key
        sut.store.mark_dispatched(key, now, SubmissionReceipt("r"))
        assert sut.store.pending_submissions(now, stale_before=now - TTL, limit=10) == []
        assert sut.store.get_schedule("job") == schedule

    def test_requesting_the_same_key_twice_keeps_one_execution(self) -> None:
        sut = self._setup()
        schedule = self._saved(sut)
        key = IdempotencyKey("manual:1")
        first = sut.store.request_run(schedule, key, REQUESTER, sut.clock.now())
        again = sut.store.request_run(schedule, key, REQUESTER, sut.clock.advance(MINUTE))
        assert again == first

    def test_a_requested_run_at_an_occurrence_instant_does_not_hide_it(self) -> None:
        sut = self._setup()
        schedule = self._saved(sut)
        now = sut.clock.set_and_get(schedule.next_run_at)
        lease = self._leader(sut)
        sut.store.request_run(schedule, IdempotencyKey("manual:1"), REQUESTER, now)
        assert len(sut.store.claim(lease, schedule, one_claim(schedule), now)) == 1
        assert len(sut.store.recent_executions(schedule.id, limit=10)) == 2

    # Completion

    def test_an_outcome_known_at_dispatch_is_recorded(self) -> None:
        sut = self._setup()
        schedule = self._saved(sut)
        now = sut.clock.advance(MINUTE)
        lease = self._leader(sut)
        [execution] = sut.store.claim(lease, schedule, one_claim(schedule), now)
        receipt = SubmissionReceipt("r-1", outcome=ExecutionStatus.TASK_FAILED)
        sut.store.mark_dispatched(execution.idempotency_key, now, receipt)
        [stored] = sut.store.recent_executions(schedule.id, limit=1)
        assert stored.status is ExecutionStatus.TASK_FAILED
        assert stored.dispatched_at == now
        assert stored.completed_at == now

    def test_completion_reported_later_moves_only_dispatched_executions(self) -> None:
        sut = self._setup()
        schedule = self._saved(sut)
        now = sut.clock.advance(MINUTE)
        lease = self._leader(sut)
        [execution] = sut.store.claim(lease, schedule, one_claim(schedule), now)
        assert not sut.store.record_completion("r-1", succeeded=True, at=now)
        sut.store.mark_dispatched(execution.idempotency_key, now, SubmissionReceipt("r-1"))
        done = sut.clock.advance(MINUTE)
        assert sut.store.record_completion("r-1", succeeded=True, at=done)
        assert not sut.store.record_completion("r-1", succeeded=False, at=done)
        assert not sut.store.record_completion("unknown", succeeded=True, at=done)
        [stored] = sut.store.recent_executions(schedule.id, limit=1)
        assert stored.status is ExecutionStatus.COMPLETED
        assert stored.completed_at == done

    # Submissions

    def test_pending_includes_stale_claims_and_due_retries_only(self) -> None:
        sut = self._setup()
        schedule = self._saved(sut)
        first_at = schedule.next_run_at
        now = sut.clock.advance(MINUTE)
        lease = self._leader(sut)
        [fresh] = sut.store.claim(lease, schedule, one_claim(schedule, first_at), now)
        assert sut.store.pending_submissions(now, stale_before=now - TTL, limit=10) == []
        later = sut.clock.advance(TTL + timedelta(seconds=1))
        [pending] = sut.store.pending_submissions(later, stale_before=later - TTL, limit=10)
        assert pending.execution.idempotency_key == fresh.idempotency_key
        assert pending.schedule.name == "job"
        retry_at = later + MINUTE
        sut.store.mark_submit_failed(fresh.idempotency_key, "broker down", retry_at)
        assert sut.store.pending_submissions(later, stale_before=later - TTL, limit=10) == []
        [retry] = sut.store.pending_submissions(retry_at, stale_before=later - TTL, limit=10)
        assert retry.execution.status is ExecutionStatus.SUBMIT_FAILED
        assert retry.execution.retry_count == 1
        assert retry.execution.error == "broker down"

    def test_mark_dispatched_records_the_receipt(self) -> None:
        sut = self._setup()
        schedule = self._saved(sut)
        now = sut.clock.advance(MINUTE)
        lease = self._leader(sut)
        [execution] = sut.store.claim(lease, schedule, one_claim(schedule), now)
        sut.store.mark_dispatched(execution.idempotency_key, now, SubmissionReceipt("result-1"))
        [stored] = sut.store.recent_executions(schedule.id, limit=1)
        assert stored.status is ExecutionStatus.DISPATCHED
        assert stored.dispatched_at == now
        assert stored.backend_result_id == "result-1"
        later = sut.clock.advance(TTL * 2)
        assert sut.store.pending_submissions(later, stale_before=later - TTL, limit=10) == []

    def test_final_submission_failure_is_terminal(self) -> None:
        sut = self._setup()
        schedule = self._saved(sut)
        now = sut.clock.advance(MINUTE)
        lease = self._leader(sut)
        [execution] = sut.store.claim(lease, schedule, one_claim(schedule), now)
        sut.store.mark_submit_failed(execution.idempotency_key, "gave up", None)
        [stored] = sut.store.recent_executions(None, limit=1)
        assert stored.status is ExecutionStatus.FAILED
        later = sut.clock.advance(TTL * 2)
        assert sut.store.pending_submissions(later, stale_before=later - TTL, limit=10) == []

    def test_recent_executions_are_newest_first(self) -> None:
        sut = self._setup()
        schedule = self._saved(sut)
        for _ in range(3):
            current = sut.store.get_schedule("job")
            assert current is not None
            now = sut.clock.advance(MINUTE)
            lease = self._leader(sut)
            sut.store.claim(lease, current, one_claim(current), now)
        executions = sut.store.recent_executions(schedule.id, limit=2)
        assert [e.scheduled_at for e in executions] == [
            schedule.next_run_at + 2 * MINUTE,
            schedule.next_run_at + MINUTE,
        ]

    def test_next_wakeup_considers_schedules_and_retries(self) -> None:
        sut = self._setup()
        assert sut.store.next_wakeup() is None
        schedule = self._saved(sut)
        assert sut.store.next_wakeup() == schedule.next_run_at
        now = sut.clock.advance(MINUTE)
        lease = self._leader(sut)
        [execution] = sut.store.claim(lease, schedule, one_claim(schedule), now)
        retry_at = now + timedelta(seconds=5)
        sut.store.mark_submit_failed(execution.idempotency_key, "down", retry_at)
        assert sut.store.next_wakeup() == retry_at

    def test_wait_for_change_times_out_without_changes(self) -> None:
        sut = self._setup()
        assert not sut.store.wait_for_change(timedelta(milliseconds=10))
