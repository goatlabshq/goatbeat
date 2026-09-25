"""JSON values: task arguments are stored, so they must survive a JSON round trip."""

import math
from collections.abc import Mapping, Sequence
from typing import cast

from goatbeat.core.errors import ConfigurationError

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None


def ensure_json(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ConfigurationError(f"{value!r} is not a finite JSON number")
        return value
    if isinstance(value, Mapping):
        return _ensure_object(cast("Mapping[object, object]", value))
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [ensure_json(item) for item in cast("Sequence[object]", value)]
    raise ConfigurationError(f"{value!r} is not JSON-serializable")


def _ensure_object(value: Mapping[object, object]) -> dict[str, JsonValue]:
    items: dict[str, JsonValue] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ConfigurationError(f"JSON object keys must be strings, got {key!r}")
        items[key] = ensure_json(item)
    return items
