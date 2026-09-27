# Goatbeat design

Status: approved in conversation on 2026-09-25, pending written review.

Goatbeat is a type-safe, distributed periodic task scheduler for Python. The core is
framework-agnostic; Django 6.1 Tasks is the first-class integration. Goatbeat schedules,
determines what is due, coordinates between scheduler instances and submits tasks. It never
executes tasks itself.

## 1. Goals and non-goals

Goals:

- One schedule occurrence produces at most one claim and one logical dispatch.
- Several scheduler instances on several servers are the normal deployment.
- Strict typing: pyright strict, no `Any` outside documented boundaries.
- Indexed due-schedule queries that stay fast at 1,000,000 schedules.
- Explicit, documented behavior for misfires, DST, failover and every dependency outage.

Non-goals (v1):

- Exactly-once task execution. It is not achievable by a scheduler and is never claimed.
- Multiple lease partitions. The schema supports them; v1 runs a single partition.
- Completion tracking for Celery, Dramatiq and RQ (they stop at `dispatched`).
- Solar and one-off "clocked" schedules from django-celery-beat.

## 2. Repository layout

A uv workspace modeled on `goatseo`. Every package is a portion of the `goatbeat` import
namespace; only the facade owns `goatbeat/__init__.py` and uses `pkgutil.extend_path`.
`.typecheck/goatbeat` is a symlink tree merging all portions so pyright resolves the namespace.

| Distribution | Import path | Contents | Runtime dependencies |
|---|---|---|---|
| `goatbeat-core` | `goatbeat.core` | domain, triggers, misfire, scheduler loop, protocols, memory and SQLite stores | none (stdlib) |
| `goatbeat-postgres` | `goatbeat.postgres` | PostgreSQL store, leases, claims, DDL | `psycopg>=3.2` |
| `goatbeat-django` | `goatbeat.django` | models, migrations, admin, commands, Django Tasks submitter | `django>=6.1`, `goatbeat-postgres` |
| `goatbeat-celery` | `goatbeat.celery` | Celery submitter | `celery>=5.5` |
| `goatbeat-dramatiq` | `goatbeat.dramatiq` | Dramatiq submitter | `dramatiq>=1.17` |
| `goatbeat-rq` | `goatbeat.rq` | RQ submitter | `rq>=2.0` |
| `goatbeat-cli` | `goatbeat.cli` | `goatbeat` command | `goatbeat-core` |
| `goatbeat-prometheus` | `goatbeat.prometheus` | `MetricsSink` implementation | `prometheus-client` |
| `goatbeat-otel` | `goatbeat.otel` | `MetricsSink` implementation | `opentelemetry-api` |
| `goatbeat` | `goatbeat` | facade, re-exports, extras | `goatbeat-core`, `goatbeat-cli` |

Facade extras: `postgres`, `django`, `celery`, `dramatiq`, `rq`, `prometheus`, `otel`.

`goatbeat-core` must never import `django`, `celery`, `dramatiq`, `rq`, `psycopg`,
`prometheus_client` or `opentelemetry`. A test enforces it.

Top-level folders: `packages/`, `tests/{integration,distributed,typing,performance}/`,
`docs/`, `examples/`, `scripts/`, `release/`, `.github/`. `legacy/` (a django-celery-beat
checkout used as reference for the migration guide) is git-ignored.

Target: Python 3.13+, Django 6.1+, PostgreSQL 16+.

## 3. Core domain

All value objects are frozen dataclasses with `slots=True`.

- `Instant`: wraps an aware `datetime` normalized to UTC. Constructing one from a naive
  datetime raises `NaiveDatetimeError`. Nothing converts silently.
- `ScheduleId`, `SchedulerId`, `FencingToken`, `IdempotencyKey`: typed identifiers.
- `IntervalTrigger(every: timedelta, start_at: Instant)`.
- `CronTrigger(expression: CronExpression, timezone: ZoneInfo)`.
- `Trigger = IntervalTrigger | CronTrigger`; every trigger exposes
  `next_after(instant: Instant) -> Instant`.
- `MisfirePolicy(StrEnum)`: `run_once`, `skip`, `catch_up`.
- `TaskCall[**P]`: a task reference plus arguments bound through `ParamSpec`.
- `Schedule`: id, name, task path, bound arguments (`JsonValue`), trigger, misfire policy,
  `misfire_grace`, `max_catch_up`, routing options, enabled flag, source (`code` or `store`),
  `next_run_at`.
- `Occurrence`: schedule id plus theoretical `scheduled_at`.
- `ExecutionStatus(StrEnum)`: `claimed`, `dispatched`, `submit_failed`, `failed`, `skipped`,
  `completed`, `task_failed`.
- `Execution`: schedule_id, scheduled_at, idempotency_key, status, scheduler_id,
  fencing_token, claimed_at, dispatched_at, completed_at, retry_count, next_retry_at,
  missed_count, backend_result_id, error.
- `TaskSubmission`: immutable input to a submitter (schedule id, scheduled_at, idempotency
  key, task path, args, kwargs, routing).
- `JsonValue`: recursive type alias for JSON-serializable values.

Errors are explicit subclasses of `GoatbeatError`: `ConfigurationError`, `NaiveDatetimeError`,
`InvalidCronExpression`, `InvalidInterval`, `TaskNotFound`, `LeaseLost`, `SubmissionError`,
`StoreUnavailable`.

## 4. Public API

```python
from goatbeat import Registry, call

beat = Registry()
beat.schedule(
    name="daily-report",
    task=generate_report,
    cron="0 9 * * *",
    timezone="America/New_York",
)
beat.schedule(name="ping-user", task=call(send_email, user_id=42), every="5m")
```

- `task` accepts a zero-argument callable or `call(fn, *args, **kwargs)`, which is typed with
  `ParamSpec` so pyright checks the arguments against the task signature. Arguments are bound
  to `JsonValue` because they are stored.
- `schedule` has two `@overload`s: one with `cron=` (and optional `timezone=`), one with
  `every=` (and optional `start_at=`). Passing both or neither is a type error and a runtime
  `ConfigurationError`.
- `every` accepts `"30s"`, `"5m"`, `"1h"`, `"1d"` (grammar: positive integer + `s|m|h|d`) or
  a positive `timedelta`.
- The registry is an explicit object. There is no module-level mutable registry.
- A string task path (`task="app.tasks.send_email"`) is accepted only by the store API used by
  the admin and the migration command; it is validated against resolvable tasks.

Code-declared schedules are upserted into the store when a scheduler starts (keyed by name,
`source=code`). Code-declared schedules that disappeared from the registry are disabled, not
deleted, so history is kept.

## 5. Scheduling semantics

### Intervals

`every` is elapsed time. Occurrences are `start_at + k * every` for integer `k >= 0`, which
prevents cumulative drift. `1d` is exactly 24 hours regardless of timezone; calendar-based
schedules use cron.

### Cron

Five fields: minute, hour, day of month, month, day of week. Supported syntax: `*`, lists,
ranges, steps, month and weekday names. When both day-of-month and day-of-week are restricted,
a day matches if either matches (POSIX behavior). Expressions are evaluated in wall-clock time
of the schedule timezone (default: `GoatbeatConfig.timezone`, default UTC).

DST rules (Vixie cron semantics):

| Situation | Fixed hour field (`30 2 * * *`) | Wildcard or stepped-over-all hour field (`*/5 * * * *`) |
|---|---|---|
| Skipped wall time (spring forward) | runs once at the end of the gap | follows real elapsed time |
| Repeated wall time (fall back) | runs once, on the first pass (`fold=0`) | runs on both passes |

Changing a schedule's timezone recomputes `next_run_at` from now; no retroactive occurrence.

The parser is implemented in `goatbeat.core` with no dependency. Property tests compare it to
`croniter` (dev dependency only) outside DST transitions.

### Misfires

An occurrence is late when `now - scheduled_at > misfire_grace` (default 60 seconds, per
schedule). `scheduled_at` always stays the theoretical time. On-time occurrences are
dispatched normally regardless of policy.

| Policy | Behavior when late occurrences exist |
|---|---|
| `run_once` (default) | Dispatch only the most recent missed occurrence; `missed_count` records the others. Advance to the next future occurrence. |
| `skip` | Dispatch nothing. Record one `skipped` execution for the most recent missed occurrence with `missed_count`. Advance to the next future occurrence. |
| `catch_up` | Dispatch every missed occurrence in order, each with its own idempotency key, up to `max_catch_up` (default 100). Older ones beyond the cap are counted in a `skipped` execution. |

## 6. Distributed coordination

Two independent protections: the lease prevents duplicate work; a unique constraint prevents
duplicate dispatch even under split-brain.

### Leader lease

Table `goatbeat_lease(partition int primary key, holder_id text, fencing_token bigint,
expires_at timestamptz)`. v1 uses partition `0`.

Acquire or renew in a single statement:

```sql
UPDATE goatbeat_lease
SET holder_id = %(me)s,
    fencing_token = fencing_token + (holder_id IS DISTINCT FROM %(me)s)::int,
    expires_at = now() + %(ttl)s
WHERE partition = 0 AND (expires_at < now() OR holder_id = %(me)s)
RETURNING fencing_token;
```

- Only PostgreSQL's `now()` decides expiry. Scheduler clocks never participate, which removes
  inter-server clock drift from the correctness argument.
- Defaults: TTL 30 s, renewal every 10 s. If a renewal fails or the local monotonic deadline
  (last successful renewal + TTL - safety margin) passes, the scheduler stops dispatching
  immediately and emits `leader.lost`.
- Advisory locks were rejected: they are session-bound, break behind transaction-mode poolers
  such as PgBouncer, and provide no fencing token.

### Occurrence claim

Table `goatbeat_execution` with `UNIQUE (idempotency_key)`. The key of a scheduled occurrence
is derived from `(schedule_id, scheduled_at)`; manual runs carry their own `manual:` key, so they
never hide a scheduled occurrence at the same instant. In one transaction:

1. `INSERT ... SELECT ... WHERE EXISTS (SELECT 1 FROM goatbeat_lease WHERE partition = 0 AND
   holder_id = %(me)s AND fencing_token = %(token)s AND expires_at > now())
   ON CONFLICT DO NOTHING RETURNING id`.
2. Advance `goatbeat_schedule.next_run_at`.

A stale leader holding an old token cannot claim. Two concurrent claims for one occurrence
yield one row.

### Occurrence lifecycle

`claimed` -> submit to backend (outside any transaction) -> `dispatched`, or `submit_failed`
with `retry_count` and `next_retry_at` (exponential backoff, capped). After
`max_submit_retries` (default 5) the execution becomes `failed`.

If the scheduler crashes after claiming and before recording the dispatch, the execution stays
`claimed`. The next leader re-submits `claimed` executions older than the lease TTL with the
same idempotency key.

### Guarantees (documented verbatim)

- Scheduling: at most one claim per occurrence.
- Dispatch: at least once; a duplicate submission happens only if a scheduler crashes between
  a successful submission and recording it.
- Delivery and execution: those of the backend. Tasks must be idempotent.

Idempotency key: `"{schedule_id}:{scheduled_at ISO 8601 UTC}"`, or `"manual:{uuid}"` for
admin "run now". Propagation: Celery `task_id`, RQ `job_id`, Dramatiq `message_id`. Django
Tasks has no caller-provided id; the key is stored in history and passed to the task only if
the task declares a `goatbeat_key: str` keyword parameter.

### Due-schedule query and loop

Partial index `(next_run_at) WHERE enabled`. Query:

```sql
SELECT ... FROM goatbeat_schedule
WHERE enabled AND next_run_at <= now()
ORDER BY next_run_at LIMIT %(batch)s
FOR UPDATE SKIP LOCKED;
```

Loop:

```text
while running:
    ensure_lease()                 # stop dispatching if lost
    recover_stale_claims()
    retry_failed_submissions()
    for schedule in due_schedules(batch=500):
        plan occurrences via misfire policy -> claim -> submit -> record
    sleep_until(min(next_run_at, next_retry_at, lease renewal, now + 60 s))
```

On PostgreSQL the sleep is interrupted by `LISTEN goatbeat_schedule_changed`, notified by the
store when a schedule is created or modified.

### Failure model

| Failure | Behavior |
|---|---|
| Scheduler process or server crash | Lease expires after TTL; a standby acquires it with a higher token and recovers stale claims. |
| PostgreSQL down | Scheduler stops dispatching, retries connection with capped exponential backoff, resumes after reacquiring the lease. |
| Network partition from PostgreSQL | Same as above; the local monotonic deadline stops dispatch before the lease can be taken by another node. |
| Backend (broker) down | Submissions fail, executions go `submit_failed`, retried with backoff, then `failed`. |
| Worker crash | Backend responsibility; Goatbeat sees `dispatched` and, for Django Tasks, no completion. |
| Clock drift between servers | No effect on lease correctness (database clock). `doctor` reports drift. |
| Deployment / restart | Graceful shutdown releases the lease (`expires_at = now()`), so failover is immediate. |

## 7. Storage

`ScheduleStore` and `LeaseManager` are `Protocol`s in `goatbeat.core`. Implementations:

- `MemoryStore`: tests and single-process development.
- `SQLiteStore` (stdlib `sqlite3`): development only; single-host, `BEGIN IMMEDIATE` for claims.
- `PostgresStore` (`goatbeat.postgres`): production. Takes a `ConnectionProvider` protocol
  (context manager yielding a DB-API connection). Standalone users pass a psycopg pool;
  Django passes its own connection. All coordination SQL exists only here.

A shared store conformance suite in `goatbeat.core.testing` runs against every store.

The DDL lives in `goatbeat.postgres` (`goatbeat postgres migrate` applies it standalone).
Django creates the same tables through its migrations; an integration test compares the
resulting schemas (columns, types, indexes, constraints).

## 8. Task submitters

```python
class TaskSubmitter(Protocol):
    def submit(self, submission: TaskSubmission) -> SubmissionReceipt: ...
```

`SubmissionReceipt` carries an optional backend result id. A submitter raises
`SubmissionError` on failure. Routing options (`queue`, `priority`, `backend`) are
backend-interpreted; unsupported options raise `ConfigurationError` at startup.

Implementations: Django Tasks, Celery, Dramatiq, RQ, and `CallableSubmitter` in core (runs
the callable in a thread pool; development only).

## 9. Django integration

- `INSTALLED_APPS += ["goatbeat.django"]`.
- `GOATBEAT = {...}` is parsed in `AppConfig.ready()` into `GoatbeatConfig`; any invalid value
  raises `ImproperlyConfigured`.
- `schedule(task=...)` accepts a `django.tasks.Task`. If the Django stubs do not expose `Task`
  as generic over its parameters, `goatbeat.django` defines a narrow typed protocol instead.
- Schedules are declared in `<app>/schedules.py`, autodiscovered like `admin.py`, against a
  registry owned by the app config.
- Submission: `task.using(queue_name=..., priority=..., backend=...).enqueue(*args, **kwargs)`;
  the returned result id is stored.
- `django.tasks.signals.task_finished` updates `completed_at` and `completed` or
  `task_failed`.
- Management command `goatbeat` with subcommands `scheduler`, `status`, `doctor`, `schedule`,
  `import_celery_beat`. The standalone `goatbeat` CLI delegates to it when
  `DJANGO_SETTINGS_MODULE` is set.
- Admin: schedule list (name, trigger, timezone, enabled, next run, last status), inline recent
  executions, enable/disable and "run now" actions, read-only execution history filterable by
  status. Code-declared schedules are read-only except `enabled`.
- Only public Django APIs are used. Any unavoidable internal is isolated in one module with a
  regression test.

## 10. Configuration

```python
@dataclass(frozen=True, slots=True)
class GoatbeatConfig:
    database_url: str | None
    scheduler_id: SchedulerId
    timezone: ZoneInfo
    lease_ttl: timedelta
    lease_renew_interval: timedelta
    max_sleep: timedelta
    batch_size: int
    max_submit_retries: int
```

`GoatbeatConfig.from_env()` reads `GOATBEAT_*` variables and `from_mapping()` reads the Django
setting. Validation fails fast (`ConfigurationError` listing every invalid field), including
`lease_renew_interval < lease_ttl / 2`. `scheduler_id` defaults to `hostname:pid:random`.

## 11. CLI

`goatbeat scheduler`, `goatbeat status [--json]`, `goatbeat doctor [--json]`,
`goatbeat schedule list [--json]`, `goatbeat schedule run <name>`, `goatbeat migrate`.
Built on `argparse`. Exit codes: 0 success, 1 check failed, 2 usage error, 3 configuration
error, 4 store unavailable, 5 unexpected error.

## 12. Observability

- Structured logging with stdlib `logging`: stable event names (`lease.acquired`,
  `lease.renewed`, `leader.lost`, `occurrence.claimed`, `occurrence.dispatched`,
  `occurrence.skipped`, `submission.failed`, `failover`) and typed `extra` fields
  (`scheduler_id`, `fencing_token`, `schedule_id`, `idempotency_key`). A JSON formatter ships
  in core.
- `MetricsSink` protocol with a no-op default. Metrics: `leader` gauge, failovers,
  claimed/dispatched/failed/skipped/missed counters, dispatch latency histogram
  (`dispatched_at - scheduled_at`), tick duration histogram.
- `goatbeat-prometheus` and `goatbeat-otel` implement the sink.

## 13. Testing

- Unit tests per package, with `FakeClock`. Cron, DST (UTC, America/New_York, Europe/Paris,
  Australia/Lord_Howe for 30-minute shifts, midnight boundaries), misfire policies, interval
  anchoring. Hypothesis property tests.
- `tests/integration`: real PostgreSQL via Docker Compose, store conformance, Django schema
  equivalence, Django Tasks end to end.
- `tests/distributed`: 10 scheduler subprocesses on one database with zero duplicate claims;
  leader SIGKILL and measured failover; concurrent claims on one occurrence; PostgreSQL stop
  and restart; submitter failure injection and retry.
- `tests/typing`: pyright contract tests (wrong `call()` arguments, `cron` with `every`).
- `tests/performance`: 100,000 and 1,000,000 schedules; `EXPLAIN` shows index scans only; tick
  duration benchmarked.
- A test asserts `goatbeat.core` imports no framework or driver.

## 14. Tooling and CI

- ruff (same rule set as goatseo), pyright strict, pytest with `filterwarnings = error`.
- lefthook: ruff on pre-commit, pyright and pytest on pre-push, conventional commit-msg check.
- Workflows: `ci.yml` (matrix Python 3.13 and 3.14, PostgreSQL 16 and 17 services),
  `security.yml` (Semgrep, Gitleaks, OSV-Scanner, zizmor), `release.yml` (reusable, called by release-please),
  `release-please.yml`. Config in `release/config.json` and `release/.manifest.json`.
- Dependabot, actionlint, actions pinned by commit hash. No CodeQL: it needs GitHub Code
  Security on private repositories.
- `docker-compose.yml`: PostgreSQL, three schedulers, two Django Tasks workers.

## 15. Documentation

mkdocs-material, 20 pages: quickstart, architecture, scheduling, Django 6.1 integration,
Django Tasks integration, type-safe tasks, distributed deployment, multiple schedulers,
multiple workers, PostgreSQL setup, failover, locking, misfire policies, timezones,
observability, security, production deployment, troubleshooting, performance, migration from
django-celery-beat. The architecture page explains why each distributed mechanism exists. The
migration guide covers PeriodicTask, IntervalSchedule, CrontabSchedule, timezones, enabled
flags, arguments, routing and operational differences, and documents `import_celery_beat`.

## 16. Delivery phases

Each phase gets its own implementation plan and ends green (tests, pyright, ruff).

1. Workspace, tooling, CI, `goatbeat-core` (domain, triggers, misfire, loop, memory and SQLite
   stores, callable submitter, config, logging, metrics protocol), facade.
2. `goatbeat-postgres`: DDL, store, lease, claims, LISTEN/NOTIFY, Docker Compose, distributed
   and performance tests.
3. `goatbeat-django`: models, migrations, admin, commands, Django Tasks submitter, completion
   signals, schema equivalence test.
4. `goatbeat-celery`, `goatbeat-dramatiq`, `goatbeat-rq`, `goatbeat-cli`,
   `goatbeat-prometheus`, `goatbeat-otel`.
5. Documentation, migration guide and `import_celery_beat`, examples.
