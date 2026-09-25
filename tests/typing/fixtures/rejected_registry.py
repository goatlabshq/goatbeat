from datetime import UTC, datetime

from goatbeat.core.registry import Registry
from goatbeat.core.tasks import call


def report() -> None: ...


def send_email(user_id: int, *, subject: str = "hi") -> None: ...


registry = Registry()
call(send_email, "not-an-int")  # expect-error
call(send_email)  # expect-error
call(send_email, 1, subject=2)  # expect-error
call(send_email, 1, unknown=True)  # expect-error
registry.schedule(name="a", task=send_email, every="5m")  # expect-error
registry.schedule(name="b", task=report, every="5m", cron="* * * * *")  # expect-error
registry.schedule(name="c", task=report)  # expect-error
registry.schedule(name="d", task=report, every="5m", misfire_policy="later")  # expect-error
registry.schedule(
    name="e", task=report, cron="* * * * *", start_at=datetime.now(UTC)
)  # expect-error
registry.schedule(name="f", task=report, every="5m", timezone="UTC")  # expect-error
registry.schedule(name="g", task="app.tasks.report", every="5m")  # expect-error
