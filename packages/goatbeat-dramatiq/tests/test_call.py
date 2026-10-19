from dramatiq_actors import charge, send_email

from goatbeat.core.registry import Registry
from goatbeat.core.tasks import TaskCall, import_task
from goatbeat.dramatiq import call


def test_the_path_imports_back_to_the_actor() -> None:
    bound = call(send_email, 42, subject="hi")
    assert bound == TaskCall("dramatiq_actors.send_email", (42,), {"subject": "hi"})
    assert import_task(bound.path) is send_email


def test_the_actor_name_does_not_change_the_import_path() -> None:
    assert call(charge).path == "dramatiq_actors.charge"


def test_the_call_schedules_through_the_core_registry() -> None:
    definition = Registry().schedule(name="charge", task=call(charge), every="1h")
    assert definition.task.path == "dramatiq_actors.charge"
