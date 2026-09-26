"""The ``GOATBEAT`` setting, validated once at startup."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Self, cast

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connections

from goatbeat.core.config import GoatbeatConfig
from goatbeat.core.errors import ConfigurationError

SETTING: Final = "GOATBEAT"
DATABASE_KEY: Final = "database"
DEFAULT_DATABASE: Final = "default"


@dataclass(frozen=True, slots=True)
class DjangoSettings:
    config: GoatbeatConfig
    database: str = DEFAULT_DATABASE

    @classmethod
    def from_django(cls) -> Self:
        raw: object = getattr(settings, SETTING, {})
        if not isinstance(raw, Mapping):
            raise ImproperlyConfigured(f"{SETTING} must be a dict, got {type(raw).__name__}")
        values = dict(cast("Mapping[str, object]", raw))
        database = values.pop(DATABASE_KEY, DEFAULT_DATABASE)
        errors: list[str] = []
        if not isinstance(database, str) or database not in connections.settings:
            errors.append(f"{DATABASE_KEY}: {database!r} is not a configured database alias")
        try:
            config = GoatbeatConfig.from_mapping(values)
        except ConfigurationError as error:
            errors.append(str(error))
            config = None
        if errors or config is None or not isinstance(database, str):
            raise ImproperlyConfigured(f"invalid {SETTING} setting: " + "; ".join(errors))
        return cls(config=config, database=database)
