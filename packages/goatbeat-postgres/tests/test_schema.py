import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from goatbeat.core.errors import ConfigurationError, StoreUnavailableError
from goatbeat.core.time import SystemClock
from goatbeat.postgres.provider import PsycopgProvider
from goatbeat.postgres.schema import SCHEMA_VERSION, applied_version, database_clock, migrate


def tables(conninfo: str) -> set[str]:
    with psycopg.connect(conninfo) as connection:
        rows = connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
        ).fetchall()
    return {row[0] for row in rows}


def test_migrate_creates_the_schema_once(conninfo: str) -> None:
    with PsycopgProvider.connect(conninfo) as provider:
        assert migrate(provider) == SCHEMA_VERSION
        assert migrate(provider) == SCHEMA_VERSION
    assert {
        "goatbeat_schedule",
        "goatbeat_execution",
        "goatbeat_lease",
        "goatbeat_schema_version",
    } <= tables(conninfo)


def test_due_index_is_partial_on_enabled(conninfo: str) -> None:
    with PsycopgProvider.connect(conninfo) as provider:
        migrate(provider)
    with psycopg.connect(conninfo) as connection:
        row = connection.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'goatbeat_schedule_due' "
            "AND schemaname = current_schema()"
        ).fetchone()
    assert row is not None
    assert "WHERE enabled" in row[0]


def create_then_fail(provider: PsycopgProvider) -> None:
    with provider.transaction() as cursor:
        cursor.execute("CREATE TABLE goatbeat_probe (id int)")
        cursor.execute("SELECT * FROM missing_table")


def test_a_failing_transaction_rolls_back(conninfo: str) -> None:
    with (
        PsycopgProvider.connect(conninfo) as provider,
        pytest.raises(psycopg.errors.UndefinedTable),
    ):
        create_then_fail(provider)
    assert "goatbeat_probe" not in tables(conninfo)


def test_a_read_only_database_is_reported_as_unavailable(conninfo: str) -> None:
    with PsycopgProvider.connect(conninfo) as provider:
        migrate(provider)
    options = f"{conninfo_to_dict(conninfo)['options']} -c default_transaction_read_only=on"
    read_only = make_conninfo(conninfo, options=options)
    with (
        PsycopgProvider.connect(read_only) as provider,
        pytest.raises(StoreUnavailableError),
        provider.transaction() as cursor,
    ):
        cursor.execute("UPDATE goatbeat_lease SET holder_id = NULL")


def test_an_older_release_refuses_a_newer_schema(conninfo: str) -> None:
    with PsycopgProvider.connect(conninfo) as provider:
        migrate(provider)
        with provider.transaction() as cursor:
            cursor.execute("INSERT INTO goatbeat_schema_version (version) VALUES (99)")
        with pytest.raises(ConfigurationError, match="99"):
            migrate(provider)


def test_the_applied_version_and_the_database_clock_are_readable(conninfo: str) -> None:
    with PsycopgProvider.connect(conninfo) as provider:
        assert applied_version(provider) == 0
        migrate(provider)
        assert applied_version(provider) == SCHEMA_VERSION
        drift = database_clock(provider) - SystemClock().now()
        assert abs(drift.total_seconds()) < 5
