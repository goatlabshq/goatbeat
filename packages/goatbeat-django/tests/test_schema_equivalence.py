import re
from dataclasses import dataclass
from typing import LiteralString, cast

import psycopg
import pytest
from django.core.management import call_command
from django.db import connection

from goatbeat.postgres.provider import PsycopgProvider
from goatbeat.postgres.schema import migrate
from goatbeat.postgres.testing import database_url_from_env, isolated_schema

TABLES = (
    "goatbeat_schedule",
    "goatbeat_execution",
    "goatbeat_early_completion",
    "goatbeat_lease",
)
COLUMNS_QUERY = (
    "SELECT table_name, column_name, data_type, is_nullable, column_default, "
    "is_identity FROM information_schema.columns WHERE table_schema = current_schema() "
    "AND table_name = ANY(%s) ORDER BY table_name, column_name"
)
INDEXES_QUERY = (
    "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema() "
    "AND tablename = ANY(%s) ORDER BY indexname"
)
FOREIGN_KEYS_QUERY = (
    "SELECT cl.relname, a.attname, ref.relname, c.confdeltype, c.condeferrable, c.condeferred "
    "FROM pg_constraint c "
    "JOIN pg_class cl ON cl.oid = c.conrelid JOIN pg_class ref ON ref.oid = c.confrelid "
    "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey) "
    "JOIN pg_namespace n ON n.oid = cl.relnamespace "
    "WHERE c.contype = 'f' AND n.nspname = current_schema() AND cl.relname = ANY(%s)"
)
UNIQUE_QUERY = (
    "SELECT cl.relname, a.attname FROM pg_index i JOIN pg_class cl ON cl.oid = i.indrelid "
    "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
    "JOIN pg_namespace n ON n.oid = cl.relnamespace "
    "WHERE i.indisunique AND n.nspname = current_schema() AND cl.relname = ANY(%s) "
    "ORDER BY 1, 2"
)
LEASE_QUERY = "SELECT partition, holder_id, fencing_token, expires_at::text FROM goatbeat_lease"


@dataclass(frozen=True)
class Snapshot:
    columns: list[tuple[object, ...]]
    indexes: dict[str, str]
    foreign_keys: list[tuple[object, ...]]
    unique: list[tuple[object, ...]]


def rows(
    cursor: psycopg.Cursor[tuple[object, ...]], query: LiteralString
) -> list[tuple[object, ...]]:
    cursor.execute(query, [list(TABLES)])
    return cursor.fetchall()


def normalize(definition: str) -> str:
    return re.sub(r"ON \S+\.(goatbeat_\w+)", r"ON \1", definition)


def describe(cursor: psycopg.Cursor[tuple[object, ...]]) -> Snapshot:
    indexes = {
        str(name): normalize(str(definition)) for name, definition in rows(cursor, INDEXES_QUERY)
    }
    return Snapshot(
        columns=rows(cursor, COLUMNS_QUERY),
        indexes={
            name: definition for name, definition in indexes.items() if name.startswith("goatbeat_")
        },
        foreign_keys=sorted(rows(cursor, FOREIGN_KEYS_QUERY), key=str),
        unique=rows(cursor, UNIQUE_QUERY),
    )


def reference_schema() -> Snapshot:
    url = database_url_from_env()
    assert url is not None
    with isolated_schema(url) as scoped:
        with PsycopgProvider.connect(scoped) as provider:
            migrate(provider)
        with psycopg.connect(scoped) as raw, raw.cursor() as cursor:
            return describe(cursor)


def django_schema() -> Snapshot:
    connection.ensure_connection()
    raw: object = connection.connection
    assert isinstance(raw, psycopg.Connection)
    raw = cast("psycopg.Connection[tuple[object, ...]]", raw)
    with raw.cursor() as cursor:
        return describe(cursor)


def is_named(name: str) -> bool:
    """Indexes created by name in the DDL, as opposed to constraint-backed ones."""
    return not name.endswith(("_pkey", "_key"))


@pytest.mark.django_db
def test_django_migrations_create_the_postgresql_schema() -> None:
    expected, actual = reference_schema(), django_schema()
    assert actual.columns == expected.columns
    assert actual.foreign_keys == expected.foreign_keys
    assert actual.unique == expected.unique
    named = {name: definition for name, definition in expected.indexes.items() if is_named(name)}
    assert {name: actual.indexes.get(name) for name in named} == named
    # Django adds text_pattern_ops indexes for LIKE lookups on unique text columns.
    extras = set(actual.indexes) - set(expected.indexes)
    assert all(name.endswith("_like") for name in extras), extras


@pytest.mark.django_db
def test_the_lease_row_is_seeded() -> None:
    with connection.cursor() as cursor:
        cursor.execute(LEASE_QUERY)
        assert cursor.fetchall() == [(0, None, 0, "-infinity")]


@pytest.mark.django_db
def test_models_and_migrations_agree() -> None:
    call_command("makemigrations", "goatbeat", "--check", "--dry-run", verbosity=0)
