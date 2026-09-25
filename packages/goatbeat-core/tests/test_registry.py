from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sample_tasks import generate_report, send_email

from goatbeat.core.errors import ConfigurationError, InvalidCronExpressionError
from goatbeat.core.misfire import MisfirePolicy, MisfireRules
from goatbeat.core.registry import Registry
from goatbeat.core.schedule import Routing
from goatbeat.core.tasks import TaskCall, call
from goatbeat.core.time import Instant
from goatbeat.core.triggers import CronTrigger, IntervalTrigger

EPOCH = Instant.of(datetime(1970, 1, 1, tzinfo=UTC))


def test_cron_schedule_uses_the_given_timezone() -> None:
    registry = Registry()
    definition = registry.schedule(
        name="daily-report", task=generate_report, cron="0 9 * * *", timezone="America/New_York"
    )
    assert definition.task == TaskCall("sample_tasks.generate_report")
    assert isinstance(definition.trigger, CronTrigger)
    assert definition.trigger.timezone == ZoneInfo("America/New_York")
    assert definition.misfire == MisfireRules()
    assert definition.enabled


def test_cron_schedule_defaults_to_the_registry_timezone() -> None:
    registry = Registry(timezone="Europe/Paris")
    definition = registry.schedule(name="x", task=generate_report, cron="0 9 * * *")
    assert isinstance(definition.trigger, CronTrigger)
    assert definition.trigger.timezone == ZoneInfo("Europe/Paris")


def test_interval_schedule_is_anchored_on_the_epoch_by_default() -> None:
    definition = Registry().schedule(name="ping", task=call(send_email, 1), every="5m")
    assert definition.trigger == IntervalTrigger(timedelta(minutes=5), EPOCH)


def test_interval_schedule_accepts_an_explicit_start() -> None:
    start = datetime(2026, 1, 1, 0, 2, tzinfo=UTC)
    definition = Registry().schedule(
        name="ping", task=generate_report, every=timedelta(minutes=5), start_at=start
    )
    assert definition.trigger == IntervalTrigger(timedelta(minutes=5), Instant.of(start))


def test_options_are_carried_into_the_definition() -> None:
    definition = Registry().schedule(
        name="catch",
        task=generate_report,
        every="1h",
        misfire_policy="catch_up",
        misfire_grace=timedelta(minutes=5),
        max_catch_up=10,
        queue="low",
        priority=5,
        backend="default",
        enabled=False,
    )
    assert definition.misfire == MisfireRules(MisfirePolicy.CATCH_UP, timedelta(minutes=5), 10)
    assert definition.routing == Routing(queue="low", priority=5, backend="default")
    assert not definition.enabled


def test_definitions_are_returned_in_declaration_order() -> None:
    registry = Registry()
    registry.schedule(name="b", task=generate_report, every="1m")
    registry.schedule(name="a", task=generate_report, every="1m")
    assert [definition.name for definition in registry.definitions()] == ["b", "a"]


def test_duplicate_names_are_rejected() -> None:
    registry = Registry()
    registry.schedule(name="a", task=generate_report, every="1m")
    with pytest.raises(ConfigurationError):
        registry.schedule(name="a", task=generate_report, every="2m")


@pytest.mark.parametrize("name", ["", "   ", "x" * 201])
def test_invalid_names_are_rejected(name: str) -> None:
    with pytest.raises(ConfigurationError):
        Registry().schedule(name=name, task=generate_report, every="1m")


def test_cron_and_every_together_are_rejected_at_runtime() -> None:
    with pytest.raises(ConfigurationError):
        Registry().schedule(  # pyright: ignore[reportCallIssue]
            name="a", task=generate_report, every="1m", cron="* * * * *"
        )


def test_neither_cron_nor_every_is_rejected_at_runtime() -> None:
    with pytest.raises(ConfigurationError):
        Registry().schedule(name="a", task=generate_report)  # pyright: ignore[reportCallIssue]


def test_invalid_cron_surfaces_at_declaration() -> None:
    with pytest.raises(InvalidCronExpressionError):
        Registry().schedule(name="a", task=generate_report, cron="61 * * * *")


def test_naive_start_is_rejected() -> None:
    with pytest.raises(ConfigurationError):
        Registry().schedule(
            name="a",
            task=generate_report,
            every="1m",
            start_at=datetime(2026, 1, 1),  # noqa: DTZ001
        )
