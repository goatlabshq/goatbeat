# Goatbeat

**Schedule once. Dispatch reliably. Scale everywhere.**

Goatbeat is a type-safe periodic task scheduler for Python. It decides what is due, makes sure
each occurrence is claimed at most once even when several schedulers run at the same time, and
hands the work to your task backend: Django 6.1 Tasks, Celery, Dramatiq or RQ. It never executes
tasks itself.

```text
                    PostgreSQL
                         |
              fenced lease + unique claims
              +----------+----------+
              |          |          |
          Goatbeat    Goatbeat   Goatbeat
          (leader)   (standby)  (standby)
              |
              v
     Django Tasks / Celery / Dramatiq / RQ
              |
    +---------+---------+
    v         v         v
 Worker A  Worker B  Worker C
```

What you get:

- **Type safety.** `call(send_email, 42)` is checked by pyright against the task signature;
  a wrong argument is a type error, not a production incident.
- **Distribution by default.** Run one scheduler or ten: they elect a leader through a lease
  whose expiry is decided by PostgreSQL's clock, and a unique constraint makes a duplicate claim
  impossible even if two of them believe they lead.
- **Explicit semantics.** Misfires, daylight saving time, crashes and outages all have a
  documented behavior.
- **A framework-agnostic core.** `goatbeat-core` depends on the standard library only.

Start with the [quickstart](quickstart.md), or read the [architecture](architecture.md) to see
why each mechanism exists.

## Packages

| Distribution | Provides |
|---|---|
| `goatbeat` | facade and the `goatbeat` command |
| `goatbeat-core` | triggers, misfire policies, scheduler loop, memory and SQLite stores |
| `goatbeat-postgres` | production store, fenced lease, LISTEN/NOTIFY |
| `goatbeat-django` | Django app, admin, `manage.py goatbeat`, Django Tasks submitter |
| `goatbeat-celery`, `goatbeat-dramatiq`, `goatbeat-rq` | task submitters |
| `goatbeat-prometheus`, `goatbeat-otel` | metrics sinks |

Install extras with `pip install "goatbeat[postgres,celery,prometheus]"`.
