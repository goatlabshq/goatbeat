import time
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from goatbeat.core.errors import ConfigurationError
from goatbeat.core.execution import ExecutionStatus
from goatbeat.core.misfire import (
    Claim,
    MisfirePolicy,
    MisfireRules,
    OccurrencePlan,
    plan_occurrences,
)
from goatbeat.core.time import Instant
from goatbeat.core.triggers import CronTrigger, IntervalTrigger

START = Instant.of(datetime(2026, 1, 1, tzinfo=UTC))
MINUTE = timedelta(minutes=1)
GRACE = timedelta(seconds=60)
TRIGGER = IntervalTrigger(every=MINUTE, start_at=START)


def plan(now: Instant, policy: MisfirePolicy, max_catch_up: int = 100) -> tuple[Claim, ...]:
    result = plan_occurrences(TRIGGER, START, now, MisfireRules(policy, GRACE, max_catch_up))
    assert result.next_run_at > now
    return result.claims


def claimed(at: Instant, missed: int = 0) -> Claim:
    return Claim(at, ExecutionStatus.CLAIMED, missed)


def skipped(at: Instant, missed: int = 0) -> Claim:
    return Claim(at, ExecutionStatus.SKIPPED, missed)


@pytest.mark.parametrize("policy", list(MisfirePolicy))
def test_nothing_due_yields_no_claim(policy: MisfirePolicy) -> None:
    result = plan_occurrences(TRIGGER, START, START - MINUTE, MisfireRules(policy))
    assert result.claims == ()
    assert result.next_run_at == START


@pytest.mark.parametrize("policy", list(MisfirePolicy))
def test_on_time_occurrence_is_claimed_regardless_of_policy(policy: MisfirePolicy) -> None:
    result = plan_occurrences(TRIGGER, START, START + timedelta(seconds=5), MisfireRules(policy))
    assert result.claims == (claimed(START),)
    assert result.next_run_at == START + MINUTE


def test_run_once_dispatches_only_the_most_recent_missed_occurrence() -> None:
    now = START + 10 * MINUTE + timedelta(seconds=30)
    # 00:00..00:09 are late (more than 60 s old); 00:10 is within the grace period.
    assert plan(now, MisfirePolicy.RUN_ONCE) == (
        claimed(START + 9 * MINUTE, missed=9),
        claimed(START + 10 * MINUTE),
    )


def test_skip_records_the_most_recent_missed_occurrence_without_dispatch() -> None:
    now = START + 10 * MINUTE + timedelta(seconds=30)
    assert plan(now, MisfirePolicy.SKIP) == (
        skipped(START + 9 * MINUTE, missed=9),
        claimed(START + 10 * MINUTE),
    )


def test_catch_up_dispatches_every_missed_occurrence_in_order() -> None:
    now = START + 3 * MINUTE + timedelta(seconds=90)
    assert plan(now, MisfirePolicy.CATCH_UP) == (
        claimed(START),
        claimed(START + MINUTE),
        claimed(START + 2 * MINUTE),
        claimed(START + 3 * MINUTE),
        claimed(START + 4 * MINUTE),  # on time
    )


def test_catch_up_is_capped_and_counts_the_oldest_as_skipped() -> None:
    now = START + 149 * MINUTE + timedelta(seconds=61)
    claims = plan(now, MisfirePolicy.CATCH_UP, max_catch_up=100)
    assert claims[0] == skipped(START + 49 * MINUTE, missed=49)
    assert claims[1:] == tuple(claimed(START + step * MINUTE) for step in range(50, 151))


def test_catch_up_below_the_cap_has_no_skipped_claim() -> None:
    now = START + 2 * MINUTE + timedelta(seconds=61)
    claims = plan(now, MisfirePolicy.CATCH_UP, max_catch_up=3)
    assert claims == tuple(claimed(START + step * MINUTE) for step in range(4))


def test_long_outage_with_run_once_is_cheap() -> None:
    now = START + timedelta(days=365, seconds=30)
    claims = plan(now, MisfirePolicy.RUN_ONCE)
    assert claims == (
        claimed(START + timedelta(days=365) - MINUTE, missed=365 * 24 * 60 - 1),
        claimed(START + timedelta(days=365)),
    )


@pytest.mark.parametrize(("grace", "max_catch_up"), [(timedelta(seconds=-1), 1), (timedelta(0), 0)])
def test_invalid_rules_are_rejected(grace: timedelta, max_catch_up: int) -> None:
    with pytest.raises(ConfigurationError):
        MisfireRules(MisfirePolicy.CATCH_UP, grace, max_catch_up)


def reference_plan(
    trigger: IntervalTrigger | CronTrigger, next_run_at: Instant, now: Instant, rules: MisfireRules
) -> OccurrencePlan:
    """Step-by-step oracle: enumerate every occurrence, then apply the policy literally."""
    late: list[Instant] = []
    on_time: list[Instant] = []
    occurrence = next_run_at
    while occurrence <= now:
        (late if now - occurrence > rules.grace else on_time).append(occurrence)
        occurrence = trigger.next_after(occurrence)
    head: list[Claim] = []
    if late and rules.policy is MisfirePolicy.RUN_ONCE:
        head = [claimed(late[-1], len(late) - 1)]
    elif late and rules.policy is MisfirePolicy.SKIP:
        head = [skipped(late[-1], len(late) - 1)]
    elif late:
        kept = late[-rules.max_catch_up :]
        dropped = late[: len(late) - len(kept)]
        head = [skipped(dropped[-1], len(dropped) - 1)] if dropped else []
        head += [claimed(at) for at in kept]
    return OccurrencePlan((*head, *(claimed(at) for at in on_time)), occurrence)


@settings(max_examples=300, deadline=None)
@given(
    every_s=st.integers(1, 600),
    outage_s=st.integers(0, 50_000),
    grace_s=st.integers(0, 300),
    cap=st.integers(1, 30),
    policy=st.sampled_from(list(MisfirePolicy)),
)
def test_planning_matches_the_step_by_step_oracle(
    every_s: int, outage_s: int, grace_s: int, cap: int, policy: MisfirePolicy
) -> None:
    trigger = IntervalTrigger(timedelta(seconds=every_s), START)
    rules = MisfireRules(policy, timedelta(seconds=grace_s), cap)
    now = START + timedelta(seconds=outage_s)
    assert plan_occurrences(trigger, START, now, rules) == reference_plan(
        trigger, START, now, rules
    )


def test_catch_up_after_a_year_of_one_second_interval_is_fast() -> None:
    trigger = IntervalTrigger(timedelta(seconds=1), START)
    now = START + timedelta(days=365)
    started = time.perf_counter()
    result = plan_occurrences(trigger, START, now, MisfireRules(MisfirePolicy.CATCH_UP))
    assert time.perf_counter() - started < 0.5
    late_total = 365 * 24 * 3600 - 60
    assert result.claims[0] == skipped(
        START + timedelta(seconds=late_total - 101), missed=late_total - 101
    )
    assert len(result.claims) == 1 + 100 + 61


@pytest.mark.parametrize("policy", list(MisfirePolicy))
def test_a_year_of_every_minute_cron_plans_quickly(policy: MisfirePolicy) -> None:
    trigger = CronTrigger.parse("* * * * *", "UTC")
    now = START + timedelta(days=365)
    started = time.perf_counter()
    result = plan_occurrences(trigger, START, now, MisfireRules(policy))
    assert time.perf_counter() - started < 0.5
    assert result.next_run_at == now + MINUTE
