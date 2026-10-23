from collections.abc import Iterator

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import connections
from django.test import override_settings

from goatbeat.django.conf import DjangoSettings
from goatbeat.django.runtime import submitter


def test_settings_are_parsed_into_typed_configuration() -> None:
    loaded = DjangoSettings.from_django()
    assert loaded.database == "default"
    assert loaded.config.scheduler_id.value == "tests"
    assert loaded.config.lease_ttl.total_seconds() == 5


@override_settings(GOATBEAT={"lease_ttl": "soon", "batch_size": 0, "unknown": 1})
def test_every_invalid_setting_is_reported_at_once() -> None:
    with pytest.raises(ImproperlyConfigured) as raised:
        DjangoSettings.from_django()
    message = str(raised.value)
    assert "lease_ttl" in message
    assert "batch_size" in message
    assert "unknown" in message


@override_settings(GOATBEAT={"submitter": "sampleapp.submitters.missing"})
def test_the_submitter_must_be_importable() -> None:
    with pytest.raises(ImproperlyConfigured, match="submitter"):
        DjangoSettings.from_django()


@override_settings(GOATBEAT={"submitter": "sampleapp.submitters.not_a_submitter"})
def test_the_submitter_must_submit() -> None:
    with pytest.raises(ImproperlyConfigured, match="submitter"):
        submitter()


@override_settings(GOATBEAT=["not", "a", "mapping"])
def test_the_setting_must_be_a_mapping() -> None:
    with pytest.raises(ImproperlyConfigured):
        DjangoSettings.from_django()


@override_settings(GOATBEAT={"database": "missing"})
def test_the_database_alias_must_exist() -> None:
    with pytest.raises(ImproperlyConfigured, match="missing"):
        DjangoSettings.from_django()


@pytest.fixture
def sqlite_alias() -> Iterator[str]:
    alias = "lite"
    sqlite = {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
    configured = connections.configure_settings(
        {"default": dict(connections.settings["default"]), alias: sqlite}
    )
    connections.settings[alias] = configured[alias]
    yield alias
    del connections.settings[alias]


@override_settings(GOATBEAT={"database": "lite"})
def test_the_database_must_be_postgresql(sqlite_alias: str) -> None:
    with pytest.raises(ImproperlyConfigured, match="PostgreSQL"):
        DjangoSettings.from_django()
    assert sqlite_alias in connections.settings
