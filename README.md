# Goatbeat

A type-safe, distributed periodic task scheduler for Python, with first-class support for
Django 6.1 Tasks.

> Schedule once. Dispatch reliably. Scale everywhere.

Goatbeat decides what is due, coordinates several scheduler instances through a fenced lease,
claims each occurrence exactly once and submits it to your task backend. Execution stays the
job of Django Tasks, Celery, Dramatiq or RQ.

Status: under active development. See the
[design](docs/superpowers/specs/2026-09-25-goatbeat-design.md).

## Quickstart

```python
import threading

from goatbeat import CallableSubmitter, GoatbeatConfig, Registry, Scheduler, SQLiteStore, call
from goatbeat.core.time import SystemClock


def generate_report() -> None: ...


def send_email(user_id: int) -> None: ...


beat = Registry(timezone="America/New_York")
beat.schedule(name="daily-report", task=generate_report, cron="0 9 * * *")
beat.schedule(name="ping", task=call(send_email, 42), every="5m", misfire_policy="skip")

store = SQLiteStore("goatbeat.sqlite3", SystemClock())
scheduler = Scheduler(
    store=store,
    leases=store,
    submitter=CallableSubmitter(),
    config=GoatbeatConfig.from_env({}),
    registry=beat,
)
scheduler.run(threading.Event())
```

`call(send_email, "42")` is a type error: task arguments are checked against the task
signature. SQLite and `CallableSubmitter` are for development; production uses PostgreSQL and
a real task backend such as Django Tasks.

## Production: PostgreSQL

```bash
pip install "goatbeat[postgres]" "psycopg[binary]"
```

```python
from goatbeat.postgres.notify import PsycopgNotifier
from goatbeat.postgres.provider import PsycopgProvider
from goatbeat.postgres.schema import migrate
from goatbeat.postgres.store import PostgresStore

provider = PsycopgProvider.connect("postgresql://goatbeat@db/goatbeat")
migrate(provider)
store = PostgresStore(provider, notifier=PsycopgNotifier("postgresql://goatbeat@db/goatbeat"))
scheduler = Scheduler(store=store, leases=store, submitter=..., config=config, registry=beat)
```

Run as many scheduler processes as you like: they elect a leader through a fenced lease whose
expiry is decided by PostgreSQL's clock, and each occurrence can only be claimed once. With
1,000,000 schedules the due query takes about 5 ms and a tick claims and submits 500
occurrences in under a second (`tests/performance`).

## Guarantees

- Scheduling: each occurrence is claimed at most once (unique constraint plus fenced lease).
- Dispatch: at least once. A duplicate submission only happens if a scheduler crashes between
  a successful submission and recording it; it reuses the same idempotency key.
- Execution: whatever the task backend guarantees. Tasks must be idempotent.

## Development

```bash
docker compose up -d --wait postgres
export GOATBEAT_TEST_DATABASE_URL=postgresql://goatbeat:goatbeat@localhost:55432/goatbeat
uv sync
uv run pytest
uv run pyright
uv run ruff check . && uv run ruff format --check .
uv run pytest -m "distributed or performance" tests/distributed tests/performance
```
