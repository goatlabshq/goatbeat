from goatbeat.django import DjangoRegistry, call
from sampleapp.tasks import send_email, send_report


def register(beat: DjangoRegistry) -> None:
    beat.schedule(name="daily-report", task=send_report, cron="0 9 * * *")
    beat.schedule(name="ping", task=call(send_email, 42, subject="ping"), every="5m")
