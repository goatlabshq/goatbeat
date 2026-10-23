from typing import LiteralString

import psycopg
import pytest
from django.db import ProgrammingError, connection, connections
from psycopg.conninfo import conninfo_to_dict

from goatbeat.core.errors import StoreUnavailableError
from goatbeat.core.testing import FakeClock, StoreConformance, StoreUnderTest
from goatbeat.django.provider import DjangoProvider, notifier_conninfo
from goatbeat.postgres.store import PostgresStore
from goatbeat.postgres.testing import database_url_from_env

SEED_LEASE = (
    "INSERT INTO goatbeat_lease (partition, holder_id, fencing_token, expires_at) "
    "VALUES (0, NULL, 0, '-infinity') ON CONFLICT DO NOTHING"
)


@pytest.mark.django_db(transaction=True)
class TestPostgresStoreThroughDjango(StoreConformance):
    """The whole store contract, over Django's connection and transaction management."""

    @pytest.fixture(autouse=True)
    def _seed_lease(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute(SEED_LEASE)  # transactional tests flush every table

    def make_store(self, clock: FakeClock) -> StoreUnderTest:
        store = PostgresStore(DjangoProvider(), lease_clock=clock)
        return StoreUnderTest(store=store, leases=store, clock=clock)


def run(*statements: LiteralString) -> None:
    with DjangoProvider().transaction() as cursor:
        for statement in statements:
            cursor.execute(statement)


@pytest.mark.django_db(transaction=True)
def test_a_failed_statement_rolls_the_transaction_back() -> None:
    with pytest.raises(ProgrammingError, match="missing_table"):
        run("INSERT INTO goatbeat_lease VALUES (7, NULL, 0, now())", "SELECT * FROM missing_table")
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM goatbeat_lease WHERE partition = 7")
        assert cursor.fetchone() == (0,)


@pytest.mark.django_db(transaction=True)
def test_a_read_only_database_is_reported_as_unavailable() -> None:
    with pytest.raises(StoreUnavailableError):
        run("SET TRANSACTION READ ONLY", "UPDATE goatbeat_lease SET holder_id = NULL")


def test_an_unknown_alias_is_rejected() -> None:
    with pytest.raises(StoreUnavailableError):
        DjangoProvider("nope")


@pytest.mark.django_db(transaction=True)
def test_consecutive_transactions_reuse_the_connection() -> None:
    provider = DjangoProvider()
    with provider.transaction() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        first = cursor.fetchone()
    with provider.transaction() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        assert cursor.fetchone() == first


@pytest.mark.django_db(transaction=True)
def test_a_connection_killed_by_the_server_is_replaced() -> None:
    provider = DjangoProvider()
    with provider.transaction() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        row = cursor.fetchone()
    assert row is not None
    with psycopg.connect(str(database_url_from_env())) as admin:
        admin.execute("SELECT pg_terminate_backend(%s)", [row[0]])
    with pytest.raises(StoreUnavailableError), provider.transaction() as cursor:
        cursor.execute("SELECT 1")
    with provider.transaction() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone() == (1,)


def test_the_listen_connection_keeps_the_database_options(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = connection.settings_dict | {
        "OPTIONS": {"sslmode": "verify-full", "application_name": "x"}
    }
    monkeypatch.setitem(connections["default"].__dict__, "settings_dict", settings)
    conninfo = conninfo_to_dict(notifier_conninfo())
    assert conninfo["sslmode"] == "verify-full"
    assert conninfo["application_name"] == "x"


def test_the_listen_connection_ignores_django_only_options(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = connection.settings_dict | {
        "OPTIONS": {
            "pool": True,
            "server_side_binding": False,
            "assume_role": "r",
            "sslmode": "require",
        }
    }
    monkeypatch.setitem(connections["default"].__dict__, "settings_dict", settings)
    conninfo = conninfo_to_dict(notifier_conninfo())
    assert conninfo["sslmode"] == "require"
    assert {"pool", "server_side_binding", "assume_role"}.isdisjoint(conninfo)
