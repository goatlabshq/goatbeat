# Phase 3: goatbeat-django Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Native Django 6.1 integration: models and migrations identical to the PostgreSQL DDL, typed schedule declarations for `django.tasks.Task`, a Django Tasks submitter with completion tracking, a `manage.py goatbeat` command and an admin.

**Architecture:** `goatbeat.django` reuses `PostgresStore` unchanged through a `DjangoProvider` (a `ConnectionProvider` over Django's own connection and `transaction.atomic`). Django only owns the tables (migrations), configuration, discovery of `<app>/schedules.py`, the admin and the Django Tasks submitter. Admin writes go through the store so scheduling rules exist once.

**Tech Stack:** Django 6.1, django-stubs, pytest-django, PostgreSQL.

**Spec:** `docs/superpowers/specs/2026-09-25-goatbeat-design.md` (section 9).

## Global Constraints

- Only public Django APIs. PostgreSQL only (the store is PostgreSQL SQL).
- `goatbeat-django` depends on `goatbeat-core`, `goatbeat-postgres`, `django>=6.1`.
- Pyright strict with django-stubs; English; no em dashes; comments at most two lines.

## Review Focus

1. Django migrations produce exactly the DDL of `goatbeat.postgres.schema` (columns, types, nullability, named indexes, FK with `ON DELETE CASCADE`, lease seed row). `test_schema_equivalence.py`.
2. A task finishing before its dispatch is recorded (ImmediateBackend runs inside `enqueue`) still ends `completed` or `task_failed`, never back to `dispatched`. `test_submitter.py`.
3. Invalid `GOATBEAT` settings fail at startup with `ImproperlyConfigured` listing every error. `test_config.py`.
4. Admin edits of code-declared schedules are limited to `enabled`; invalid cron or interval input shows a form error. `test_admin.py`.
5. A manual run requested from the admin or the CLI by a non-leader process is dispatched by the leader. Core conformance plus `test_command.py`.

---

## Tasks

### Task 1: Core support for requested runs and completion
**Produces (core):** `ExecutionStatus.REQUESTED`; `ScheduleStore.request_run(schedule, key, now) -> Execution` (unfenced insert, status `requested`); `pending_submissions` also returns `requested` rows; `SubmissionReceipt.outcome: Literal[COMPLETED, TASK_FAILED] | None`; `mark_dispatched` stores the outcome and `completed_at` when present; `ScheduleStore.record_completion(result_id, *, succeeded, at) -> bool` (only moves `dispatched` rows); `Scheduler.run_now(name)` uses `request_run`. Implemented in memory, SQLite and PostgreSQL stores; conformance tests.
- Commit `feat(core): add requested runs and completion tracking`.

### Task 2: Package, settings, test harness
- `packages/goatbeat-django` (module `goatbeat.django`, app label `goatbeat`), `.typecheck` symlink, release config, dev deps `django-stubs`, `pytest-django`.
- `tests/conftest.py` configures Django settings (PostgreSQL from `GOATBEAT_TEST_DATABASE_URL`, `ImmediateBackend` tasks) and skips without it.
- Commit `build: add goatbeat-django package and test harness`.

### Task 3: Models, migrations, schema equivalence
- Models `Schedule`, `Execution`, `Lease` with `db_table` matching the DDL, `JSONField`, partial indexes, `DB_CASCADE`, identity id, lease seed row in the migration.
- Test: compare `information_schema.columns`, index definitions and constraints of the Django-migrated tables with a schema migrated by `goatbeat.postgres.schema.migrate`.
- Commit `feat(django): add models and migrations matching the PostgreSQL schema`.

### Task 4: Configuration, provider, declarations
**Produces:** `DjangoSettings.from_django()` (`GOATBEAT` dict: core keys plus `database`); `DjangoProvider(alias)`; `goatbeat.django.call(task, *args, **kwargs)` typed on `Task[P, R]`; `DjangoRegistry.schedule(...)` accepting `Task[[], object]`, `TaskCall` or a zero-argument callable, defaulting routing from the task; discovery of `register(beat)` in `<app>/schedules.py`.
- Commit `feat(django): add settings, provider and typed schedule declarations`.

### Task 5: Django Tasks submitter and completion signal
**Produces:** `DjangoTasksSubmitter`: resolves the task path with `import_string`, applies routing with `using()`, passes `goatbeat_key` when the task function accepts it, returns the result id; outcome captured when the task finishes inside `enqueue`; `task_finished` receiver calling `record_completion`.
- Commit `feat(django): submit through Django Tasks and track completion`.

### Task 6: Management command
- `manage.py goatbeat scheduler | schedule list [--json] | schedule run NAME | schedule prune`.
- Commit `feat(django): add the goatbeat management command`.

### Task 7: Admin
- Schedule admin (list, filters, enable/disable/run-now actions, code schedules read-only except `enabled`, form validation through core types, saves through the store) and read-only execution admin.
- Commit `feat(django): add the schedule and execution admin`.

### Task 8: End to end, facade, docs
- End-to-end: scheduler tick through Django with ImmediateBackend ends `completed`; facade extra `django`; README section; CI unchanged (Django tests run in the PostgreSQL job).
- Commit `feat: expose the Django integration from the facade`.
