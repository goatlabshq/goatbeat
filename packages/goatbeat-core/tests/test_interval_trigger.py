from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from goatbeat.core.time import Instant
from goatbeat.core.triggers import IntervalTrigger

START = Instant.of(datetime(2026, 1, 1, tzinfo=UTC))
FIVE_MINUTES = timedelta(minutes=5)


def test_before_start_returns_start() -> None:
    trigger = IntervalTrigger(every=FIVE_MINUTES, start_at=START)
    assert trigger.next_after(START - timedelta(hours=1)) == START


def test_on_a_boundary_returns_the_following_occurrence() -> None:
    trigger = IntervalTrigger(every=FIVE_MINUTES, start_at=START)
    assert trigger.next_after(START) == START + FIVE_MINUTES


def test_occurrences_stay_anchored_to_start_without_drift() -> None:
    trigger = IntervalTrigger(every=timedelta(seconds=7), start_at=START)
    late = START + timedelta(days=30, milliseconds=3)
    assert trigger.next_after(late) == START + timedelta(days=30, seconds=2)


@given(
    offset=st.integers(min_value=-(10**12), max_value=10**13),
    every_us=st.integers(min_value=1, max_value=10**11),
)
def test_next_is_strictly_later_and_on_the_grid(offset: int, every_us: int) -> None:
    every = timedelta(microseconds=every_us)
    trigger = IntervalTrigger(every=every, start_at=START)
    instant = START + timedelta(microseconds=offset)
    result = trigger.next_after(instant)
    assert result > instant
    assert (result - START) % every == timedelta(0)
    assert result - instant <= every or instant < START
