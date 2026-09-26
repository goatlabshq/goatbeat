"""LISTEN/NOTIFY wake-ups, so schedulers see schedule changes before their next poll."""

import logging
import time
from datetime import timedelta
from types import TracebackType
from typing import Final, Protocol, Self

import psycopg
from psycopg import sql

from goatbeat.core.observability import LOGGER_NAME, Event, log_event

CHANNEL: Final = "goatbeat_schedule_changed"


class Notifier(Protocol):
    def wait(self, timeout: timedelta) -> bool:
        """Block until a change notification or the timeout; True when notified."""
        ...


class PsycopgNotifier:
    """Owns one dedicated connection: LISTEN cannot share a pooled, transactional one.

    Losing it only degrades wake-ups to polling, so errors are logged and retried lazily.
    """

    def __init__(self, conninfo: str, logger: logging.Logger | None = None) -> None:
        self._conninfo = conninfo
        self._logger = logger or logging.getLogger(LOGGER_NAME)
        self._connection: psycopg.Connection[tuple[object, ...]] | None = None

    def wait(self, timeout: timedelta) -> bool:
        started = time.monotonic()
        try:
            connection = self._listening_connection()
            for _ in connection.notifies(timeout=timeout.total_seconds(), stop_after=1):
                return True
        except psycopg.Error as error:
            log_event(self._logger, Event.STORE_UNAVAILABLE, logging.WARNING, error=str(error))
            self.close()
            time.sleep(max(0.0, timeout.total_seconds() - (time.monotonic() - started)))
        return False

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _listening_connection(self) -> psycopg.Connection[tuple[object, ...]]:
        if self._connection is None or self._connection.closed:
            connection = psycopg.connect(self._conninfo, autocommit=True)
            connection.execute(sql.SQL("LISTEN {}").format(sql.Identifier(CHANNEL)))
            self._connection = connection
        return self._connection

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
