import re
from datetime import timedelta
from typing import Final

from goatbeat.core.errors import InvalidIntervalError

_PATTERN: Final = re.compile(r"[1-9][0-9]*([smhd])")
_UNITS: Final = {
    "s": timedelta(seconds=1),
    "m": timedelta(minutes=1),
    "h": timedelta(hours=1),
    "d": timedelta(days=1),
}


def parse_duration(value: str | timedelta) -> timedelta:
    if isinstance(value, timedelta):
        if value <= timedelta(0):
            raise InvalidIntervalError(f"duration must be positive, got {value}")
        return value
    match = _PATTERN.fullmatch(value)
    if match is None:
        raise InvalidIntervalError(
            f"invalid duration {value!r}: expected a positive integer followed by s, m, h or d"
        )
    return int(value[:-1]) * _UNITS[match.group(1)]
