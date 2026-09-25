from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from goatbeat.core.errors import ConfigurationError
from goatbeat.core.time import Instant, resolve_timezone
from goatbeat.core.triggers import CronTrigger

NEW_YORK = "America/New_York"


def utc(*parts: int) -> Instant:
    return Instant.of(datetime(*parts, tzinfo=UTC))


def occurrences(trigger: CronTrigger, start: Instant, end: Instant) -> list[Instant]:
    found: list[Instant] = []
    current = trigger.next_after(start)
    while current <= end:
        found.append(current)
        current = trigger.next_after(current)
    return found


def test_utc_daily() -> None:
    trigger = CronTrigger.parse("0 9 * * *", "UTC")
    assert trigger.next_after(utc(2026, 1, 1, 9)) == utc(2026, 1, 2, 9)


def test_local_time_is_honored() -> None:
    trigger = CronTrigger.parse("0 9 * * *", NEW_YORK)
    assert trigger.next_after(utc(2026, 1, 1)) == utc(2026, 1, 1, 14)
    assert trigger.next_after(utc(2026, 7, 1)) == utc(2026, 7, 1, 13)


def test_midnight_boundary_across_new_year_in_paris() -> None:
    trigger = CronTrigger.parse("0 0 * * *", "Europe/Paris")
    assert trigger.next_after(utc(2026, 12, 31, 22, 30)) == utc(2026, 12, 31, 23)


def test_fixed_hour_in_spring_gap_runs_once_at_the_end_of_the_gap() -> None:
    trigger = CronTrigger.parse("30 2 * * *", NEW_YORK)
    first = trigger.next_after(utc(2026, 3, 8, 5))
    assert first == utc(2026, 3, 8, 7)  # 03:00 EDT
    assert trigger.next_after(first) == utc(2026, 3, 9, 6, 30)  # 02:30 EDT


def test_several_fixed_times_in_the_gap_collapse_into_one_run() -> None:
    trigger = CronTrigger.parse("0,30 2 * * *", NEW_YORK)
    runs = occurrences(trigger, utc(2026, 3, 8, 5), utc(2026, 3, 9, 5))
    assert runs == [utc(2026, 3, 8, 7)]


def test_fixed_hour_in_fall_overlap_runs_only_on_the_first_pass() -> None:
    trigger = CronTrigger.parse("30 1 * * *", NEW_YORK)
    runs = occurrences(trigger, utc(2026, 11, 1, 4), utc(2026, 11, 2, 7))
    assert runs == [utc(2026, 11, 1, 5, 30), utc(2026, 11, 2, 6, 30)]


def test_wildcard_hour_follows_real_time_in_fall() -> None:
    trigger = CronTrigger.parse("*/30 * * * *", NEW_YORK)
    runs = occurrences(trigger, utc(2026, 11, 1, 3, 59), utc(2026, 11, 1, 8))
    assert runs == [utc(2026, 11, 1, 4) + timedelta(minutes=30 * step) for step in range(9)]


def test_wildcard_hour_follows_real_time_in_spring() -> None:
    trigger = CronTrigger.parse("*/30 * * * *", NEW_YORK)
    runs = occurrences(trigger, utc(2026, 3, 8, 4, 59), utc(2026, 3, 8, 8))
    assert runs == [utc(2026, 3, 8, 5) + timedelta(minutes=30 * step) for step in range(7)]


def test_half_hour_shift_in_lord_howe() -> None:
    trigger = CronTrigger.parse("45 1 * * *", "Australia/Lord_Howe")
    first = trigger.next_after(utc(2026, 4, 4, 14))
    assert first == utc(2026, 4, 4, 14, 45)  # 01:45 +11:00, first pass
    assert trigger.next_after(first) == utc(2026, 4, 5, 15, 15)  # next day, 01:45 +10:30


def test_unknown_timezone_is_a_configuration_error() -> None:
    with pytest.raises(ConfigurationError):
        CronTrigger.parse("* * * * *", "Mars/Olympus_Mons")


def test_resolve_timezone_accepts_zoneinfo() -> None:
    zone = ZoneInfo(NEW_YORK)
    assert resolve_timezone(zone) is zone


@settings(max_examples=60, deadline=None)
@given(
    text=st.sampled_from(
        ["*/7 * * * *", "30 1 * * *", "0,30 2 * * *", "15 */3 * * *", "0 0 * * 0", "59 23 * * *"]
    ),
    zone=st.sampled_from([NEW_YORK, "Europe/Paris", "Australia/Lord_Howe", "UTC"]),
    day=st.integers(min_value=0, max_value=364),
)
def test_occurrences_strictly_increase(text: str, zone: str, day: int) -> None:
    trigger = CronTrigger.parse(text, zone)
    current = utc(2026, 1, 1) + timedelta(days=day)
    for _ in range(60):
        following = trigger.next_after(current)
        assert following > current
        current = following
