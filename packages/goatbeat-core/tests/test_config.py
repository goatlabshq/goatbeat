from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest

from goatbeat.core.config import GoatbeatConfig
from goatbeat.core.errors import ConfigurationError
from goatbeat.core.ids import SchedulerId


def test_defaults_are_safe() -> None:
    config = GoatbeatConfig.from_env({})
    assert config.database_url is None
    assert config.timezone == ZoneInfo("UTC")
    assert config.lease_ttl == timedelta(seconds=30)
    assert config.lease_renew_interval == timedelta(seconds=10)
    assert config.max_sleep == timedelta(seconds=60)
    assert config.batch_size == 500
    assert config.max_submit_retries == 5
    assert config.scheduler_id.value


def test_environment_values_are_parsed() -> None:
    config = GoatbeatConfig.from_env(
        {
            "GOATBEAT_DATABASE_URL": "postgresql://db/goatbeat",
            "GOATBEAT_SCHEDULER_ID": "node-a",
            "GOATBEAT_TIMEZONE": "Europe/Paris",
            "GOATBEAT_LEASE_TTL": "1m",
            "GOATBEAT_LEASE_RENEW_INTERVAL": "20s",
            "GOATBEAT_MAX_SLEEP": "5m",
            "GOATBEAT_BATCH_SIZE": "100",
            "GOATBEAT_MAX_SUBMIT_RETRIES": "0",
            "UNRELATED": "ignored",
        }
    )
    assert config.database_url == "postgresql://db/goatbeat"
    assert config.scheduler_id == SchedulerId("node-a")
    assert config.timezone == ZoneInfo("Europe/Paris")
    assert config.lease_ttl == timedelta(minutes=1)
    assert config.lease_renew_interval == timedelta(seconds=20)
    assert config.max_sleep == timedelta(minutes=5)
    assert config.batch_size == 100
    assert config.max_submit_retries == 0


def test_every_invalid_value_is_reported_at_once() -> None:
    with pytest.raises(ConfigurationError) as raised:
        GoatbeatConfig.from_env(
            {
                "GOATBEAT_TIMEZONE": "Nowhere/City",
                "GOATBEAT_LEASE_TTL": "soon",
                "GOATBEAT_BATCH_SIZE": "0",
                "GOATBEAT_MAX_SUBMIT_RETRIES": "-1",
                "GOATBEAT_SCHEDULER_ID": " ",
            }
        )
    message = str(raised.value)
    for key in ("timezone", "lease_ttl", "batch_size", "max_submit_retries", "scheduler_id"):
        assert key in message


def test_renewal_must_be_well_below_the_ttl() -> None:
    with pytest.raises(ConfigurationError, match="lease_renew_interval"):
        GoatbeatConfig.from_env(
            {"GOATBEAT_LEASE_TTL": "30s", "GOATBEAT_LEASE_RENEW_INTERVAL": "15s"}
        )


def test_mapping_accepts_native_values_and_rejects_unknown_keys() -> None:
    config = GoatbeatConfig.from_mapping(
        {"lease_ttl": timedelta(seconds=40), "batch_size": 10, "timezone": ZoneInfo("UTC")}
    )
    assert config.lease_ttl == timedelta(seconds=40)
    assert config.batch_size == 10
    with pytest.raises(ConfigurationError, match="lease_tll"):
        GoatbeatConfig.from_mapping({"lease_tll": "30s"})


def test_mapping_rejects_wrong_types() -> None:
    with pytest.raises(ConfigurationError, match="batch_size"):
        GoatbeatConfig.from_mapping({"batch_size": 1.5})
    with pytest.raises(ConfigurationError, match="batch_size"):
        GoatbeatConfig.from_mapping({"batch_size": True})
