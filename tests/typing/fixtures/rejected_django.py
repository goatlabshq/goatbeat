from django.tasks import task

from goatbeat.django import DjangoRegistry, call


@task
def report() -> None: ...


@task
def send_email(user_id: int, *, subject: str = "hi") -> None: ...


def plain() -> None: ...


beat = DjangoRegistry()
beat.schedule(name="a", task=report, cron="0 9 * * *")
beat.schedule(name="b", task=call(send_email, 1, subject="x"), every="5m")
call(send_email, "not-an-int")  # expect-error
call(send_email)  # expect-error
call(send_email, 1, subject=2)  # expect-error
beat.schedule(name="c", task=send_email, every="5m")  # expect-error
beat.schedule(name="d", task=plain, every="5m")  # expect-error
beat.schedule(name="e", task=report, every="5m", cron="* * * * *")  # expect-error
