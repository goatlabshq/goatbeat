import math
from datetime import UTC, datetime

import pytest

from goatbeat.core.errors import ConfigurationError
from goatbeat.core.json import JsonValue, ensure_json


def test_accepts_nested_json_values() -> None:
    value: JsonValue = {"a": [1, 2.5, "x", None, True, {"b": []}]}
    assert ensure_json(value) == value


@pytest.mark.parametrize(
    "value",
    [{1, 2}, b"bytes", datetime(2026, 1, 1, tzinfo=UTC), {1: "x"}, math.nan, (1, object())],
)
def test_rejects_values_that_are_not_json(value: object) -> None:
    with pytest.raises(ConfigurationError):
        ensure_json(value)


def test_tuples_become_lists() -> None:
    assert ensure_json((1, 2)) == [1, 2]


@pytest.mark.parametrize("value", ["a\x00b", {"k\x00": 1}, ["\x00"]])
def test_nul_characters_are_rejected_because_postgresql_jsonb_cannot_store_them(
    value: object,
) -> None:
    with pytest.raises(ConfigurationError):
        ensure_json(value)
