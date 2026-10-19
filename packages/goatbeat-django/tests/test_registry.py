from zoneinfo import ZoneInfo

import pytest
from django.test import override_settings
from sampleapp.tasks import send_email, send_report

from goatbeat.core.errors import ConfigurationError
from goatbeat.core.tasks import TaskCall
from goatbeat.core.triggers import CronTrigger
from goatbeat.django import DjangoRegistry, call, registry


def test_schedules_modules_are_discovered_at_startup() -> None:
    definitions = {definition.name: definition for definition in registry().definitions()}
    assert set(definitions) == {"daily-report", "ping"}
    assert definitions["daily-report"].task == TaskCall("sampleapp.tasks.send_report")
    assert definitions["ping"].task == TaskCall(
        "sampleapp.tasks.send_email", (42,), {"subject": "ping"}
    )


def test_call_binds_arguments_to_the_django_task() -> None:
    assert call(send_email, 7) == TaskCall("sampleapp.tasks.send_email", (7,), {})


def test_cron_defaults_to_the_goatbeat_timezone() -> None:
    beat = DjangoRegistry(timezone="America/New_York")
    definition = beat.schedule(name="r", task=send_report, cron="0 9 * * *")
    assert isinstance(definition.trigger, CronTrigger)
    assert definition.trigger.timezone == ZoneInfo("America/New_York")


@override_settings(TIME_ZONE="Europe/Paris", GOATBEAT={})
def test_the_django_time_zone_is_the_default_goatbeat_timezone() -> None:
    from goatbeat.django.conf import DjangoSettings

    assert DjangoSettings.from_django().config.timezone == ZoneInfo("Europe/Paris")


def test_routing_options_are_forwarded() -> None:
    definition = DjangoRegistry().schedule(
        name="r", task=send_report, every="1h", queue="low", priority=-5, backend="default"
    )
    assert (definition.routing.queue, definition.routing.priority) == ("low", -5)


def test_duplicate_names_are_rejected() -> None:
    beat = DjangoRegistry()
    beat.schedule(name="r", task=send_report, every="1h")
    with pytest.raises(ConfigurationError):
        beat.schedule(name="r", task=send_report, every="2h")


def plain_function() -> None:
    pass


def test_a_function_that_is_not_a_django_task_is_rejected_clearly() -> None:
    with pytest.raises(ConfigurationError, match="decorate it with @task"):
        DjangoRegistry().schedule(name="r", task=plain_function, every="1h")  # pyright: ignore[reportArgumentType]
