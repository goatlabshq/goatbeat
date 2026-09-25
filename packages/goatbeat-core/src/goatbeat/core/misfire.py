"""Misfire policies decide what happens to occurrences that are overdue."""

from collections import deque
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Literal

from goatbeat.core.errors import ConfigurationError
from goatbeat.core.execution import ExecutionStatus
from goatbeat.core.time import Instant
from goatbeat.core.triggers import IntervalTrigger, Trigger


class MisfirePolicy(StrEnum):
    RUN_ONCE = "run_once"
    SKIP = "skip"
    CATCH_UP = "catch_up"


DEFAULT_GRACE = timedelta(seconds=60)
DEFAULT_MAX_CATCH_UP = 100
# Cron occurrences cannot be counted arithmetically: past this many, the planner jumps to the
# end of the outage and missed_count becomes a lower bound.
MAX_CRON_SCAN = 10_000
CRON_TAIL = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class MisfireRules:
    policy: MisfirePolicy = MisfirePolicy.RUN_ONCE
    grace: timedelta = DEFAULT_GRACE
    max_catch_up: int = DEFAULT_MAX_CATCH_UP

    def __post_init__(self) -> None:
        if self.grace < timedelta(0):
            raise ConfigurationError(f"misfire grace must not be negative, got {self.grace}")
        if self.max_catch_up < 1:
            raise ConfigurationError(f"max_catch_up must be at least 1, got {self.max_catch_up}")


@dataclass(frozen=True, slots=True)
class Claim:
    """One execution row to create; ``missed_count`` counts occurrences it stands for."""

    scheduled_at: Instant
    status: Literal[ExecutionStatus.CLAIMED, ExecutionStatus.SKIPPED]
    missed_count: int = 0


@dataclass(frozen=True, slots=True)
class OccurrencePlan:
    claims: tuple[Claim, ...]
    next_run_at: Instant


@dataclass(slots=True)
class _Late:
    count: int = 0
    last: Instant | None = None
    last_dropped: Instant | None = None


def plan_occurrences(
    trigger: Trigger,
    next_run_at: Instant,
    now: Instant,
    rules: MisfireRules,
) -> OccurrencePlan:
    policy, grace = rules.policy, rules.grace
    late = _Late()
    kept: deque[Instant] = deque()
    on_time: list[Instant] = []
    late_before = now - grace
    occurrence = _skip_ahead(trigger, next_run_at, late_before, late, rules)
    scanned = 0
    while occurrence <= now:
        if occurrence < late_before:
            late.count += 1
            late.last = occurrence
            if policy is MisfirePolicy.CATCH_UP:
                kept.append(occurrence)
                if len(kept) > rules.max_catch_up:
                    late.last_dropped = kept.popleft()
        else:
            on_time.append(occurrence)
        occurrence = trigger.next_after(occurrence)
        scanned += 1
        if scanned == MAX_CRON_SCAN and occurrence < late_before - CRON_TAIL:
            occurrence = trigger.next_after(late_before - CRON_TAIL)
    claims = [*_late_claims(policy, late, kept), *(_claimed(at) for at in on_time)]
    return OccurrencePlan(tuple(claims), occurrence)


def _skip_ahead(
    trigger: Trigger, occurrence: Instant, late_before: Instant, late: _Late, rules: MisfireRules
) -> Instant:
    """Count long runs of late interval occurrences arithmetically instead of one by one."""
    if not isinstance(trigger, IntervalTrigger) or occurrence >= late_before:
        return occurrence
    late_total = -((occurrence - late_before) // trigger.every)
    keep = rules.max_catch_up if rules.policy is MisfirePolicy.CATCH_UP else 1
    skippable = late_total - keep
    if skippable <= 0:
        return occurrence
    late.count += skippable
    late.last_dropped = occurrence + trigger.every * (skippable - 1)
    return occurrence + trigger.every * skippable


def _late_claims(policy: MisfirePolicy, late: _Late, kept: deque[Instant]) -> list[Claim]:
    if late.last is None:
        return []
    match policy:
        case MisfirePolicy.RUN_ONCE:
            return [_claimed(late.last, late.count - 1)]
        case MisfirePolicy.SKIP:
            return [Claim(late.last, ExecutionStatus.SKIPPED, late.count - 1)]
        case MisfirePolicy.CATCH_UP:
            dropped = late.count - len(kept)
            head = (
                [Claim(late.last_dropped, ExecutionStatus.SKIPPED, dropped - 1)]
                if late.last_dropped is not None
                else []
            )
            return head + [_claimed(at) for at in kept]


def _claimed(at: Instant, missed_count: int = 0) -> Claim:
    return Claim(at, ExecutionStatus.CLAIMED, missed_count)
