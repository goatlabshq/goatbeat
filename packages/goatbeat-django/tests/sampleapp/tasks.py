from django.tasks import task

RUNS: list[str] = []


@task
def send_report() -> None:
    RUNS.append("report")


@task(queue_name="emails", priority=10)
def send_email(user_id: int, *, subject: str = "hello") -> None:
    RUNS.append(f"email:{user_id}:{subject}")


@task
def keyed(goatbeat_key: str = "") -> None:
    RUNS.append(f"keyed:{goatbeat_key}")


@task
def explode() -> None:
    raise RuntimeError("boom")
