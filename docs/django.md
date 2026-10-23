# Django 6.1 integration

`goatbeat-django` is a regular Django app. It needs PostgreSQL: the coordination SQL relies on
row locks and `LISTEN/NOTIFY`.

## Setup

```python
INSTALLED_APPS = [..., "goatbeat.django"]

GOATBEAT = {  # every key is optional
    "database": "default",  # a PostgreSQL alias
    "timezone": "Europe/Paris",  # defaults to TIME_ZONE
    "lease_ttl": "30s",
    "lease_renew_interval": "10s",
    "max_sleep": "60s",
    "batch_size": 500,
    "max_submit_retries": 5,
    "scheduler_id": "web-1",  # defaults to host:pid:random
    "submitter": "goatbeat.django.submitter.DjangoTasksSubmitter",
}
```

`submitter` is the dotted path of a `TaskSubmitter` instance or of a callable returning one.
To dispatch to Celery from `manage.py goatbeat scheduler`:

```python
# myproject/beat.py
from goatbeat.celery import CelerySubmitter
from myproject.celery import app

submitter = CelerySubmitter(app)
```

```python
GOATBEAT = {"submitter": "myproject.beat.submitter"}
```

The setting is validated when Django starts. Any invalid value raises `ImproperlyConfigured`
listing every problem at once; nothing falls back to a default silently.

`python manage.py migrate` creates the tables. Their schema is identical to the one
`goatbeat migrate` creates for plain Python projects; a test keeps the two in sync.

## Declaring schedules

Each app may have a `schedules.py` defining `register(beat)`, discovered like `admin.py`:

```python
from goatbeat.django import DjangoRegistry, call
from myapp.tasks import generate_report, send_email


def register(beat: DjangoRegistry) -> None:
    beat.schedule(name="daily-report", task=generate_report, cron="0 9 * * *")
    beat.schedule(name="ping", task=call(send_email, 42), every="5m", queue="emails")
```

## The management command

```bash
python manage.py goatbeat scheduler            # run until SIGTERM; --once for one tick
python manage.py goatbeat schedule list --json # publish code schedules, list all
python manage.py goatbeat schedule run NAME    # ask the leader for an extra run
python manage.py goatbeat schedule prune       # disable code schedules no longer declared
python manage.py goatbeat import_celery_beat   # see the migration guide
```

The standalone `goatbeat` command also works: with `DJANGO_SETTINGS_MODULE` set and neither
`--app` nor `GOATBEAT_APP`, it uses the Django project.

Give the scheduler process persistent connections (`CONN_MAX_AGE`, `CONN_HEALTH_CHECKS`).
Goatbeat reuses its connection and replaces it only after an error.

## Logging

Goatbeat logs to the `goatbeat` logger. The event name is the message and the details
(`schedule`, `idempotency_key`, `scheduler_id`, ...) are structured fields, which a plain
formatter drops. Use the JSON formatter to keep them:

```python
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "goatbeat.core.observability.JsonFormatter"}},
    "handlers": {"goatbeat": {"class": "logging.StreamHandler", "formatter": "json"}},
    "loggers": {"goatbeat": {"handlers": ["goatbeat"], "level": "INFO", "propagate": False}},
}
```

## Admin

- **Schedules**: list, filters, enabled flag, next run and last status, recent executions inline.
  Actions: enable, disable, run now (they need the `change` permission).
- **Creating and editing**: cron or interval, timezone, JSON arguments, misfire policy and
  routing. Every value is validated by the same core types as code declarations, and saves go
  through the store, so `next_run_at` follows the scheduling rules.
- **Code schedules** are read-only except `enabled`: their definition lives in your code.
- **Executions** are read-only history, filterable by status.
