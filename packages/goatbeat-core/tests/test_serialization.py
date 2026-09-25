from datetime import UTC, datetime, timedelta

import pytest

from goatbeat.core.errors import ConfigurationError
from goatbeat.core.misfire import MisfirePolicy, MisfireRules
from goatbeat.core.schedule import Routing, ScheduleDefinition
from goatbeat.core.serialization import definition_from_columns, definition_to_columns
from goatbeat.core.tasks import TaskCall
from goatbeat.core.time import Instant
from goatbeat.core.triggers import CronTrigger, IntervalTrigger

START = Instant.of(datetime(2026, 1, 1, tzinfo=UTC))


@pytest.mark.parametrize(
    "definition",
    [
        ScheduleDefinition(
            name="cron",
            task=TaskCall("app.tasks.send", (1, "x"), {"flag": True, "nested": {"a": [1]}}),
            trigger=CronTrigger.parse("0 9 * * 1-5", "America/New_York"),
            misfire=MisfireRules(MisfirePolicy.CATCH_UP, timedelta(minutes=5), 10),
            routing=Routing(queue="low", priority=-5, backend="default"),
            enabled=False,
        ),
        ScheduleDefinition(
            name="interval",
            task=TaskCall("app.tasks.ping"),
            trigger=IntervalTrigger(timedelta(seconds=90), START),
        ),
    ],
    ids=["cron", "interval"],
)
def test_round_trip(definition: ScheduleDefinition) -> None:
    assert definition_from_columns(definition_to_columns(definition)) == definition


def test_unknown_trigger_kind_is_rejected() -> None:
    columns = definition_to_columns(
        ScheduleDefinition("x", TaskCall("a.b"), IntervalTrigger(timedelta(seconds=1), START))
    )
    columns["trigger_kind"] = "solar"
    with pytest.raises(ConfigurationError):
        definition_from_columns(columns)


def test_arguments_must_decode_to_the_expected_shape() -> None:
    columns = definition_to_columns(
        ScheduleDefinition("x", TaskCall("a.b"), IntervalTrigger(timedelta(seconds=1), START))
    )
    columns["task_args"] = '{"not": "a list"}'
    with pytest.raises(ConfigurationError):
        definition_from_columns(columns)
