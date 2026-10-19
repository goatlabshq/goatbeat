# Goatbeat

A type-safe, distributed periodic task scheduler for Python, with first-class support for
Django 6.1 Tasks.

> Schedule once. Dispatch reliably. Scale everywhere.

Goatbeat decides what is due, coordinates several scheduler instances through a fenced lease,
claims each occurrence exactly once and submits it to your task backend. Execution stays the
job of Django Tasks, Celery, Dramatiq or RQ.

Status: under active development. The [documentation](https://goatlabshq.github.io/goatbeat/)
covers setup, scheduling, Django, deployment and operations.

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
signature. The Django app needs PostgreSQL, in development and tests too; SQLite and
`CallableSubmitter` are for plain Python experiments only.

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

## Django 6.1

```bash
pip install "goatbeat[django]" "psycopg[binary]"
```

```python
# settings.py
INSTALLED_APPS = [..., "goatbeat.django"]
GOATBEAT = {"lease_ttl": "30s"}  # optional; timezone defaults to TIME_ZONE
```

```python
# myapp/schedules.py
from goatbeat.django import DjangoRegistry, call
from myapp.tasks import generate_report, send_email  # django.tasks.Task objects


def register(beat: DjangoRegistry) -> None:
    beat.schedule(name="daily-report", task=generate_report, cron="0 9 * * *")
    beat.schedule(name="ping", task=call(send_email, 42), every="5m", queue="emails")
```

```bash
python manage.py migrate
python manage.py goatbeat scheduler          # run on as many hosts as you like
python manage.py goatbeat schedule list --json
python manage.py goatbeat schedule run daily-report
```

Occurrences are enqueued with Django Tasks; `task_finished` marks them `completed` or
`task_failed`. A task that declares a `goatbeat_key: str` parameter receives the idempotency key.
The admin lists schedules, their executions and offers enable, disable and run-now actions.
Give the scheduler process persistent connections (`CONN_MAX_AGE`, `CONN_HEALTH_CHECKS`).

## Command line

```python
# myproject/beat.py
from celery import Celery

from goatbeat import GoatbeatApp, Registry
from goatbeat.celery import CelerySubmitter

beat = Registry()
beat.schedule(name="daily-report", task=generate_report, cron="0 9 * * *")
app = GoatbeatApp(registry=beat, submitter=CelerySubmitter(Celery(broker="redis://...")))
```

```bash
export GOATBEAT_DATABASE_URL=postgresql://goatbeat@db/goatbeat   # or sqlite:///beat.db
goatbeat --app myproject.beat:app migrate
goatbeat --app myproject.beat:app scheduler --metrics-port 9464
goatbeat --app myproject.beat:app status --json
goatbeat --app myproject.beat:app doctor        # exit 1 when a check fails
```

Exit codes: 0 success, 1 check failed, 2 usage error, 3 configuration error, 4 store
unavailable, 5 unexpected error. `--log-format json` emits one JSON object per event on stderr.
`sqlite:///beat.db` is relative to the working directory, `sqlite:////var/lib/beat.db` absolute.
Every command publishes the schedules declared in the app before reading the store, so run it
with the same code version as your schedulers. With `DJANGO_SETTINGS_MODULE` set and no `--app`, the command uses the Django
project. Submitters: `goatbeat.celery.CelerySubmitter`, `goatbeat.dramatiq.DramatiqSubmitter`,
`goatbeat.rq.RQSubmitter` and `goatbeat.django.submitter.DjangoTasksSubmitter`; each passes the
idempotency key as the message id. No backend deduplicates on that id: a resubmission after a
crash runs the task twice, so tasks must be idempotent (they can read `goatbeat_key`). Metrics: `goatbeat.prometheus.PrometheusMetrics` and
`goatbeat.otel.OpenTelemetryMetrics` (`GoatbeatApp(metrics=...)`).

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
