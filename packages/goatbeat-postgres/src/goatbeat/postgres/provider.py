from collections.abc import Generator, Sequence
from contextlib import AbstractContextManager, contextmanager
from types import TracebackType
from typing import Final, LiteralString, Protocol, Self

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import TupleRow
from psycopg_pool import ConnectionPool, PoolTimeout

from goatbeat.core.errors import StoreUnavailableError

# Errors meaning "this database cannot serve us right now": a promoted replica still read-only,
# a session the server ended, a lost connection.
UNAVAILABLE_ERRORS: Final = (
    psycopg.OperationalError,
    psycopg.InterfaceError,
    psycopg.errors.ReadOnlySqlTransaction,
    psycopg.errors.IdleInTransactionSessionTimeout,
    PoolTimeout,
)
CONNECT_TIMEOUT_SECONDS: Final = 5
POOL_WAIT_SECONDS: Final = 10.0
# Detect half-open connections (network partition) in about a minute instead of hours.
KEEPALIVES: Final = {
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
}


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
    def __init__(self, pool: ConnectionPool[psycopg.Connection[TupleRow]]) -> None:
        self._pool = pool

    @classmethod
    def connect(
        cls, conninfo: str, *, min_size: int = 1, max_size: int = 4, wait: bool = False
    ) -> Self:
        """``wait`` fails fast with StoreUnavailableError when the database is unreachable."""
        defaults: dict[str, object] = {"connect_timeout": CONNECT_TIMEOUT_SECONDS, **KEEPALIVES}
        given = conninfo_to_dict(conninfo)
        pool = ConnectionPool(
            conninfo,
            connection_class=psycopg.Connection[TupleRow],
            kwargs={key: value for key, value in defaults.items() if key not in given},
            min_size=min_size,
            max_size=max_size,
            timeout=POOL_WAIT_SECONDS,
            check=ConnectionPool.check_connection,
            configure=_without_prepared_statements,
            open=False,
        )
        try:
            pool.open(wait=wait, timeout=POOL_WAIT_SECONDS)
        except PoolTimeout as error:
            pool.close()
            raise StoreUnavailableError(f"cannot connect to PostgreSQL: {error}") from error
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
        except UNAVAILABLE_ERRORS as error:
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


# Server-side prepared statements are session state: PgBouncer transaction mode breaks them.
def _without_prepared_statements(connection: psycopg.Connection[TupleRow]) -> None:
    connection.prepare_threshold = None
