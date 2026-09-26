from typing import LiteralString

import pytest
from django.db import ProgrammingError, connection

from goatbeat.core.errors import StoreUnavailableError
from goatbeat.core.testing import FakeClock, StoreConformance, StoreUnderTest
from goatbeat.django.provider import DjangoProvider
from goatbeat.postgres.store import PostgresStore

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
