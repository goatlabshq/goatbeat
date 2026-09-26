"""Runs the PostgreSQL store on Django's own connection and transaction management."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import cast

from django.db import DatabaseError, InterfaceError, OperationalError, connections, transaction
from django.utils.connection import ConnectionDoesNotExist
from psycopg.conninfo import make_conninfo

from goatbeat.core.errors import StoreUnavailableError
from goatbeat.postgres.provider import UNAVAILABLE_ERRORS, Cursor


class DjangoProvider:
    def __init__(self, alias: str = "default") -> None:
        try:
            connections[alias]
        except ConnectionDoesNotExist as error:
            raise StoreUnavailableError(f"unknown database alias {alias!r}") from error
        self._alias = alias

    @contextmanager
    def transaction(self) -> Generator[Cursor]:
        connection = connections[self._alias]
        # A long-running scheduler thread must not keep reusing a connection the server dropped.
        connection.close_if_unusable_or_obsolete()
        try:
            with transaction.atomic(using=self._alias), connection.cursor() as cursor:
                yield cast("Cursor", cursor)
        except DatabaseError as error:
            if _is_unavailable(error):
                raise StoreUnavailableError(str(error)) from error
            raise


def notifier_conninfo(alias: str = "default") -> str:
    """A libpq connection string for LISTEN, built from the Django database settings."""
    settings = connections[alias].settings_dict
    parameters = {
        "dbname": settings.get("NAME"),
        "user": settings.get("USER"),
        "password": settings.get("PASSWORD"),
        "host": settings.get("HOST"),
        "port": settings.get("PORT"),
    }
    return make_conninfo(**{key: str(value) for key, value in parameters.items() if value})


def _is_unavailable(error: DatabaseError) -> bool:
    return isinstance(error, OperationalError | InterfaceError) or isinstance(
        error.__cause__, UNAVAILABLE_ERRORS
    )
