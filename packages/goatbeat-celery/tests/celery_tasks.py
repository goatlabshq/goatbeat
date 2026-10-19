from celery import Celery

app = Celery("tests", broker="memory://", set_as_current=False)


@app.task
def send_email(user_id: int, subject: str = "hello") -> None:
    del user_id, subject


@app.task(name="billing.charge")
def charge() -> None:
    pass
