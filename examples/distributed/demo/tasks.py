import os

import psycopg
from rq import get_current_job


def record(name: str) -> None:
    job = get_current_job()
    with psycopg.connect(os.environ["GOATBEAT_DATABASE_URL"], autocommit=True) as connection:
        connection.execute(
            "INSERT INTO demo_runs (name, job_id) VALUES (%s, %s)",
            [name, None if job is None else job.id],
        )
