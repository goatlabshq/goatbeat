from datetime import UTC, datetime, timedelta

from goatbeat.core.misfire import MisfirePolicy
from goatbeat.core.registry import Registry
from goatbeat.core.tasks import call


def report() -> None: ...


def send_email(user_id: int, *, subject: str = "hi") -> None: ...


registry = Registry()
registry.schedule(name="a", task=report, cron="0 9 * * *", timezone="America/New_York")
registry.schedule(name="b", task=report, every="5m")
registry.schedule(name="c", task=report, every=timedelta(seconds=30), start_at=datetime.now(UTC))
registry.schedule(name="d", task=call(send_email, 42, subject="x"), cron="*/5 * * * *")
registry.schedule(name="e", task=call(send_email, user_id=1), every="1h", misfire_policy="skip")
registry.schedule(name="f", task=report, every="1d", misfire_policy=MisfirePolicy.CATCH_UP)
