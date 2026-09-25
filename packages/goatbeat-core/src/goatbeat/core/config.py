"""Typed configuration, validated at startup; invalid values never fall back to defaults."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Final, Self
from zoneinfo import ZoneInfo

from goatbeat.core.durations import parse_duration
from goatbeat.core.errors import ConfigurationError
from goatbeat.core.ids import SchedulerId, new_scheduler_id
from goatbeat.core.time import resolve_timezone

ENV_PREFIX: Final = "GOATBEAT_"


@dataclass(frozen=True, slots=True)
class GoatbeatConfig:
    database_url: str | None = None
    scheduler_id: SchedulerId = field(default_factory=new_scheduler_id)
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("UTC"))
    lease_ttl: timedelta = timedelta(seconds=30)
    lease_renew_interval: timedelta = timedelta(seconds=10)
    max_sleep: timedelta = timedelta(seconds=60)
    batch_size: int = 500
    max_submit_retries: int = 5

    def __post_init__(self) -> None:
        if self.lease_renew_interval * 2 >= self.lease_ttl:
            raise ConfigurationError(
                "lease_renew_interval must be less than half of lease_ttl "
                f"({self.lease_renew_interval} >= {self.lease_ttl / 2})"
            )

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Self:
        values: dict[str, object] = {
            name: env[f"{ENV_PREFIX}{name.upper()}"]
            for name in _PARSERS
            if f"{ENV_PREFIX}{name.upper()}" in env
        }
        return cls.from_mapping(values)

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> Self:
        errors = [f"unknown setting {name!r}" for name in values if name not in _PARSERS]
        parsed: dict[str, object] = {}
        for name, value in values.items():
            parser = _PARSERS.get(name)
            if parser is None:
                continue
            try:
                parsed[name] = parser(value)
            except (ConfigurationError, ValueError, TypeError) as error:
                errors.append(f"{name}: {error}")
        if errors:
            raise ConfigurationError("invalid Goatbeat configuration: " + "; ".join(errors))
        return cls(**parsed)  # pyright: ignore[reportArgumentType]


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"expected a non-empty string, got {value!r}")
    return value


def _duration(value: object) -> timedelta:
    if isinstance(value, str | timedelta):
        return parse_duration(value)
    raise ConfigurationError(f"expected a duration such as '30s' or a timedelta, got {value!r}")


def _integer(minimum: int) -> Callable[[object], int]:
    def parse(value: object) -> int:
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            value = int(value)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigurationError(f"expected an integer, got {value!r}")
        if value < minimum:
            raise ConfigurationError(f"must be at least {minimum}, got {value}")
        return value

    return parse


def _timezone(value: object) -> ZoneInfo:
    if isinstance(value, str | ZoneInfo):
        return resolve_timezone(value)
    raise ConfigurationError(f"expected a timezone name, got {value!r}")


_PARSERS: Final[Mapping[str, Callable[[object], object]]] = {
    "database_url": _text,
    "scheduler_id": lambda value: SchedulerId(_text(value)),
    "timezone": _timezone,
    "lease_ttl": _duration,
    "lease_renew_interval": _duration,
    "max_sleep": _duration,
    "batch_size": _integer(1),
    "max_submit_retries": _integer(0),
}
