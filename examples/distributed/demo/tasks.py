import os

import psycopg


def record(name: str) -> None:
    with psycopg.connect(os.environ["GOATBEAT_DATABASE_URL"], autocommit=True) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS demo_runs (name text, ran_at timestamptz DEFAULT now())"
        )
        connection.execute("INSERT INTO demo_runs (name) VALUES (%s)", [name])
