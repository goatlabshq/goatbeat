"""Helpers for testing against a real PostgreSQL: one throwaway schema per test."""

import os
import secrets
from collections.abc import Generator
from contextlib import contextmanager
from typing import Final

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

TEST_DATABASE_URL_VARIABLE: Final = "GOATBEAT_TEST_DATABASE_URL"


def database_url_from_env() -> str | None:
    return os.environ.get(TEST_DATABASE_URL_VARIABLE) or None


@contextmanager
def isolated_schema(url: str) -> Generator[str]:
    """Create a schema, yield a conninfo whose search_path points at it, then drop it."""
    schema = f"goatbeat_test_{secrets.token_hex(6)}"
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        yield make_conninfo(url, options=f"-c search_path={schema}")
    finally:
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
