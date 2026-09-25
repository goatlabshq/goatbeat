import pytest
from sample_tasks import Namespace, generate_report, send_email

from goatbeat.core.errors import ConfigurationError, TaskNotFoundError
from goatbeat.core.tasks import TaskCall, call, import_task, task_path


def test_task_path_uses_module_and_qualified_name() -> None:
    assert task_path(generate_report) == "sample_tasks.generate_report"
    assert task_path(Namespace.nested) == "sample_tasks.Namespace.nested"


def test_task_path_prefers_an_explicit_module_path() -> None:
    class DjangoLikeTask:
        module_path = "app.tasks.send"

    assert task_path(DjangoLikeTask()) == "app.tasks.send"


def test_lambdas_and_local_functions_are_rejected() -> None:
    def local() -> None: ...

    with pytest.raises(ConfigurationError):
        task_path(lambda: None)
    with pytest.raises(ConfigurationError):
        task_path(local)


def test_call_binds_json_arguments() -> None:
    bound = call(send_email, 42, subject="report")
    assert bound == TaskCall("sample_tasks.send_email", (42,), {"subject": "report"})


def test_call_rejects_arguments_that_cannot_be_stored() -> None:
    with pytest.raises(ConfigurationError):
        call(send_email, {1, 2})  # pyright: ignore[reportArgumentType]


def test_import_task_resolves_functions_and_nested_attributes() -> None:
    assert import_task("sample_tasks.generate_report") is generate_report
    assert import_task("sample_tasks.Namespace.nested") is Namespace.nested


@pytest.mark.parametrize(
    "path",
    [
        "sample_tasks.missing",
        "missing_module.task",
        "sample_tasks.NOT_CALLABLE",
        "",
        "sample_tasks",
    ],
)
def test_import_task_reports_missing_tasks(path: str) -> None:
    with pytest.raises(TaskNotFoundError):
        import_task(path)
