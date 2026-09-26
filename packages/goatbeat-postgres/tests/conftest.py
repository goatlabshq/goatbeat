from collections.abc import Iterator

import pytest

from goatbeat.postgres.testing import database_url_from_env, isolated_schema

pytest.register_assert_rewrite("goatbeat.core.testing")


@pytest.fixture
def conninfo() -> Iterator[str]:
    url = database_url_from_env()
    if url is None:
        pytest.skip("GOATBEAT_TEST_DATABASE_URL is not set")
    with isolated_schema(url) as scoped:
        yield scoped
