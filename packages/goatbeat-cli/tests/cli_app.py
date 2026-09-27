"""Applications loaded by the CLI tests through --app."""

from goatbeat.core.app import GoatbeatApp
from goatbeat.core.execution import SubmissionReceipt
from goatbeat.core.registry import Registry
from goatbeat.core.submission import TaskSubmission
from goatbeat.core.tasks import TaskCall

SUBMITTED: list[str] = []


class RecordingSubmitter:
    def submit(self, submission: TaskSubmission) -> SubmissionReceipt:
        SUBMITTED.append(submission.idempotency_key.value)
        return SubmissionReceipt(submission.idempotency_key.value)


def ping() -> None: ...


def _registry() -> Registry:
    registry = Registry()
    registry.schedule(name="ping", task=ping, every="1m")
    return registry


app = GoatbeatApp(registry=_registry(), submitter=RecordingSubmitter())


def broken_app() -> GoatbeatApp:
    registry = _registry()
    registry.schedule(name="ghost", task=TaskCall("cli_app.missing"), every="1h")
    return GoatbeatApp(registry=registry, submitter=RecordingSubmitter())


not_an_app = 42
