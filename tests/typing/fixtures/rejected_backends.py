import dramatiq
from celery import shared_task

from goatbeat.celery import call as celery_call
from goatbeat.dramatiq import call as dramatiq_call


@shared_task
def charge(amount: int) -> None: ...


@dramatiq.actor
def send_email(user_id: int) -> None: ...


celery_call(charge, 10)
dramatiq_call(send_email, 1)
celery_call(charge, "ten")  # expect-error
dramatiq_call(send_email, "one")  # expect-error
dramatiq_call(send_email)  # expect-error
