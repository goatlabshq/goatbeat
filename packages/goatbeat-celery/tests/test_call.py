from celery_tasks import charge, send_email

from goatbeat.celery import call
from goatbeat.core.registry import Registry
from goatbeat.core.tasks import TaskCall


def test_the_path_is_the_task_name_the_worker_knows() -> None:
    assert call(send_email, 42, subject="hi") == TaskCall(
        "celery_tasks.send_email", (42,), {"subject": "hi"}
    )


def test_a_custom_task_name_is_kept() -> None:
    assert call(charge).path == "billing.charge"


def test_the_call_schedules_through_the_core_registry() -> None:
    definition = Registry().schedule(name="charge", task=call(charge), every="1h")
    assert definition.task.path == "billing.charge"
