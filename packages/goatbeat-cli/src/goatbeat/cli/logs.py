"""Logging for the command line, and recognizing database outages from optional drivers."""

import logging
import sys
from typing import Final, override

from goatbeat.core.observability import EXTRA_KEY, LOGGER_NAME, JsonFormatter

DATABASE_MODULES: Final = ("psycopg", "django.db")


class TextFormatter(logging.Formatter):
    """``time level event key=value ...``, readable in a terminal."""

    @override
    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        fields: object = record.__dict__.get(EXTRA_KEY)
        if isinstance(fields, dict):
            extra = " ".join(
                f"{key}={value}"
                for key, value in fields.items()  # pyright: ignore[reportUnknownVariableType]
                if key != "event"
            )
            line = f"{line} {extra}" if extra else line
        return line


def configure_logging(level: str, *, as_json: bool) -> None:
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        if getattr(handler, "goatbeat_cli", False):
            logger.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.goatbeat_cli = True  # type: ignore[attr-defined]
    handler.setFormatter(
        JsonFormatter() if as_json else TextFormatter("%(asctime)s %(levelname)s %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(level)


def is_database_unavailable(error: Exception) -> bool:
    """psycopg is optional here, so its connection errors are recognized without importing it."""
    for kind in type(error).__mro__:
        if (
            kind.__module__.startswith(("psycopg", "django.db"))
            and kind.__name__ == "OperationalError"
        ):
            return True
    return False
