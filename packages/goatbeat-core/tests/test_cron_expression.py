# Cron expressions work on naive wall-clock time by design; timezones apply in CronTrigger.
# ruff: noqa: DTZ001
from datetime import date, datetime, timedelta

import pytest
from croniter import croniter
from hypothesis import given, settings
from hypothesis import strategies as st

from goatbeat.core.errors import InvalidCronExpressionError
from goatbeat.core.triggers.cron_expression import CronExpression


def test_parses_steps_lists_and_ranges() -> None:
    expression = CronExpression.parse("*/15 1,2,5-7 1-10/3 * *")
    assert expression.minutes == {0, 15, 30, 45}
    assert expression.hours == {1, 2, 5, 6, 7}
    assert expression.days == {1, 4, 7, 10}
    assert expression.months == set(range(1, 13))


def test_single_value_with_step_runs_to_the_end_of_the_range() -> None:
    assert CronExpression.parse("5/20 * * * *").minutes == {5, 25, 45}


def test_names_are_case_insensitive_and_seven_means_sunday() -> None:
    expression = CronExpression.parse("0 0 * JAN,jun Mon-fri")
    assert expression.months == {1, 6}
    assert expression.weekdays == {1, 2, 3, 4, 5}
    assert CronExpression.parse("0 0 * * 7").weekdays == {0}


def test_wildcard_detection() -> None:
    assert CronExpression.parse("*/5 * * * *").hour_is_wildcard
    assert CronExpression.parse("0 */1 * * *").hour_is_wildcard
    assert not CronExpression.parse("0 */2 * * *").hour_is_wildcard
    assert not CronExpression.parse("30 2 * * *").hour_is_wildcard


def test_day_fields_combine_with_or_when_both_are_restricted() -> None:
    expression = CronExpression.parse("0 0 13 * fri")
    assert expression.matches_date(date(2026, 3, 13))  # Friday the 13th
    assert expression.matches_date(date(2026, 3, 6))  # a Friday
    assert expression.matches_date(date(2026, 4, 13))  # a Monday the 13th
    assert not expression.matches_date(date(2026, 4, 14))


def test_a_star_step_day_field_is_not_a_restriction() -> None:
    expression = CronExpression.parse("0 0 2 * */2")
    assert not expression.weekday_restricted
    assert expression.matches_date(date(2026, 8, 2))  # the 2nd and a Sunday: both fields match
    assert not expression.matches_date(date(2026, 3, 1))  # a Sunday only: no OR semantics
    assert not expression.matches_date(date(2026, 3, 2))  # the 2nd only, on a Monday


def test_weekday_only_restriction() -> None:
    expression = CronExpression.parse("0 9 * * 1")
    assert expression.matches_date(date(2026, 9, 28))
    assert not expression.matches_date(date(2026, 9, 29))


@pytest.mark.parametrize(
    "text",
    [
        "* * * *",
        "* * * * * *",
        "60 * * * *",
        "* 24 * * *",
        "* * 0 * *",
        "* * * 13 *",
        "* * * * 8",
        "*/0 * * * *",
        "5-1 * * * *",
        "a * * * *",
        "1,,2 * * * *",
        "0 0 30 2 *",
        "0 0 31 4,6,9,11 *",
        "",
    ],
)
def test_rejects_invalid_or_unsatisfiable_expressions(text: str) -> None:
    with pytest.raises(InvalidCronExpressionError):
        CronExpression.parse(text)


def test_february_29_is_satisfiable() -> None:
    expression = CronExpression.parse("0 0 29 2 *")
    assert expression.next_wall_time(datetime(2026, 1, 1)) == datetime(2028, 2, 29)


def test_next_wall_time_is_strictly_after_and_truncates_seconds() -> None:
    expression = CronExpression.parse("*/5 * * * *")
    assert expression.next_wall_time(datetime(2026, 1, 1, 0, 5)) == datetime(2026, 1, 1, 0, 10)
    assert expression.next_wall_time(datetime(2026, 1, 1, 0, 4, 59, 999)) == datetime(
        2026, 1, 1, 0, 5
    )


def test_next_wall_time_rolls_over_year() -> None:
    expression = CronExpression.parse("0 0 1 1 *")
    assert expression.next_wall_time(datetime(2026, 1, 1)) == datetime(2027, 1, 1)


def _field(
    low: int, high: int, *, star_step: bool = True, step: bool = True
) -> st.SearchStrategy[str]:
    value = st.integers(low, high)
    single = value.map(str)
    # croniter reads a degenerate range such as "0-0" as "*", so ranges stay non-empty.
    pairs = st.tuples(value, value).filter(lambda pair: pair[0] != pair[1])
    ranged = pairs.map(lambda pair: f"{min(pair)}-{max(pair)}")
    # croniter also mishandles "N/step", so steps start from "*" or an explicit range.
    starts = st.one_of(st.just("*"), ranged) if star_step else ranged
    stepped = st.tuples(starts, st.integers(1, high)).map(lambda pair: f"{pair[0]}/{pair[1]}")
    element = st.one_of(single, ranged, stepped) if step else st.one_of(single, ranged)
    listed = st.lists(element, min_size=1, max_size=3).map(",".join)
    return st.one_of(st.just("*"), listed)


expressions = st.tuples(
    _field(0, 59),
    _field(0, 23),
    # croniter treats "*/n" day fields as restricted; Vixie cron (and Goatbeat) does not.
    _field(1, 28, star_step=False),
    _field(1, 12),
    # croniter also mishandles weekday steps such as "6/1", so weekday steps are unit-tested only.
    _field(0, 6, step=False),
).map(" ".join)


@settings(max_examples=300, deadline=None)
@given(
    text=expressions,
    start=st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2090, 1, 1)),
)
def test_matches_croniter_on_wall_clock_time(text: str, start: datetime) -> None:
    expression = CronExpression.parse(text)
    reference = croniter(text, start)
    current = start
    for _ in range(3):
        expected = reference.get_next(datetime)
        current = expression.next_wall_time(current)
        assert current == expected
        assert current - start < timedelta(days=366 * 9)


def test_rare_but_satisfiable_expressions_are_found() -> None:
    leap_sunday = CronExpression.parse("0 0 29 2 */7")
    assert leap_sunday.next_wall_time(datetime(2026, 1, 1)) == datetime(2032, 2, 29)
    first_monday_of_february = CronExpression.parse("0 0 */31 2 mon")
    assert first_monday_of_february.next_wall_time(datetime(2027, 2, 2)) == datetime(2038, 2, 1)
