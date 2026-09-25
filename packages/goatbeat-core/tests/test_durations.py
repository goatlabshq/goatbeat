from datetime import timedelta

import pytest

from goatbeat.core.durations import parse_duration
from goatbeat.core.errors import InvalidIntervalError


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("30s", timedelta(seconds=30)),
        ("5m", timedelta(minutes=5)),
        ("1h", timedelta(hours=1)),
        ("1d", timedelta(days=1)),
        ("90m", timedelta(minutes=90)),
    ],
)
def test_parses_supported_units(text: str, expected: timedelta) -> None:
    assert parse_duration(text) == expected


@pytest.mark.parametrize("text", ["0s", "-1m", "5", "1w", "1.5h", "", " 5m", "05m"])
def test_rejects_malformed_text(text: str) -> None:
    with pytest.raises(InvalidIntervalError):
        parse_duration(text)


def test_accepts_positive_timedelta() -> None:
    assert parse_duration(timedelta(seconds=2)) == timedelta(seconds=2)


@pytest.mark.parametrize("value", [timedelta(0), timedelta(seconds=-1)])
def test_rejects_non_positive_timedelta(value: timedelta) -> None:
    with pytest.raises(InvalidIntervalError):
        parse_duration(value)
