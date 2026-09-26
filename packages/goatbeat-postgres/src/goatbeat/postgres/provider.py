"""Database access seam: every SQL statement of Goatbeat runs through a ConnectionProvider."""

from collections.abc import Generator, Sequence
from contextlib import AbstractContextManager, contextmanager
from types import TracebackType
from typing import LiteralString, Protocol, Self

import psycopg
from psycopg.rows import TupleRow
from psycopg_pool import ConnectionPool, PoolTimeout

from goatbeat.core.errors import StoreUnavailableError


class Cursor(Protocol):
    """The DB-API subset Goatbeat uses; psycopg and Django cursors both satisfy it."""

    @property
    def rowcount(self) -> int: ...

    def execute(
        self, query: LiteralString, params: Sequence[object] | None = None, /
    ) -> object: ...

    def fetchone(self) -> Sequence[object] | None: ...

    def fetchall(self) -> Sequence[Sequence[object]]: ...


class ConnectionProvider(Protocol):
    def transaction(self) -> AbstractContextManager[Cursor]:
        """Yield a cursor inside a transaction committed on success, rolled back on error."""
        ...


class PsycopgProvider:
    """Standalone provider backed by a psycopg connection pool."""

    def __init__(self, pool: ConnectionPool[psycopg.Connection[TupleRow]]) -> None:
        self._pool = pool

    @classmethod
    def connect(cls, conninfo: str, *, min_size: int = 1, max_size: int = 4) -> Self:
        pool = ConnectionPool(
            conninfo,
            connection_class=psycopg.Connection[TupleRow],
            min_size=min_size,
            max_size=max_size,
            open=False,
        )
        pool.open()
        return cls(pool)

    @contextmanager
    def transaction(self) -> Generator[Cursor]:
        try:
            with (
                self._pool.connection() as connection,
                connection.transaction(),
                connection.cursor() as cursor,
            ):
                yield cursor
        except (psycopg.OperationalError, psycopg.InterfaceError, PoolTimeout) as error:
            raise StoreUnavailableError(str(error)) from error

    def close(self) -> None:
        self._pool.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
