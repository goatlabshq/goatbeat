import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from goatbeat.django.conf import DjangoSettings


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


@override_settings(GOATBEAT=["not", "a", "mapping"])
def test_the_setting_must_be_a_mapping() -> None:
    with pytest.raises(ImproperlyConfigured):
        DjangoSettings.from_django()


@override_settings(GOATBEAT={"database": "missing"})
def test_the_database_alias_must_exist() -> None:
    with pytest.raises(ImproperlyConfigured, match="missing"):
        DjangoSettings.from_django()
