import os

import psycopg


def main() -> None:
    with psycopg.connect(os.environ["GOATBEAT_DATABASE_URL"], autocommit=True) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS demo_runs "
            "(name text, job_id text, ran_at timestamptz DEFAULT now())"
        )


if __name__ == "__main__":
    main()
