from collections.abc import Generator
from contextlib import contextmanager
from typing import cast

from django.db import DatabaseError, InterfaceError, OperationalError, connections, transaction
from django.db.backends.base.base import BaseDatabaseWrapper
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
        if not connection.in_atomic_block:
            _drop_if_broken(connection)
        try:
            with transaction.atomic(using=self._alias), connection.cursor() as cursor:
                yield cast("Cursor", cursor)
        except DatabaseError as error:
            if _is_unavailable(error):
                raise StoreUnavailableError(str(error)) from error
            raise


def _drop_if_broken(connection: BaseDatabaseWrapper) -> None:
    """Replace a connection only after it failed; CONN_MAX_AGE would reconnect every call.

    The scheduler thread never gets Django's between-requests hook, so it checks here.
    """
    if connection.errors_occurred:
        if connection.is_usable():
            connection.errors_occurred = False
        else:
            connection.close()


def notifier_conninfo(alias: str = "default") -> str:
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
