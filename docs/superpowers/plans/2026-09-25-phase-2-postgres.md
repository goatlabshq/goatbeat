# Phase 2: goatbeat-postgres Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Production PostgreSQL backend: schema and migrations, a store and lease manager that pass the phase 1 conformance suite, LISTEN/NOTIFY wake-ups, and distributed, failure and performance tests against a real database.

**Architecture:** `goatbeat.postgres` holds all coordination SQL once. It talks to the database through a `ConnectionProvider` protocol (a transaction yielding a DB-API cursor with `%s` parameters), so phase 3 can pass Django's connection. `PsycopgProvider` wraps a `psycopg_pool.ConnectionPool` for standalone use. Lease expiry and the claim fence use PostgreSQL `now()` only.

**Tech Stack:** psycopg 3.2+, psycopg-pool, PostgreSQL 16/17, Docker Compose, pytest markers.

**Spec:** `docs/superpowers/specs/2026-09-25-goatbeat-design.md` (sections 6, 7, 13).

## Global Constraints

- Same as phase 1: Python 3.13+, pyright strict, stdlib-only `goatbeat.core`, English, no em dashes.
- `goatbeat-postgres` depends on `goatbeat-core`, `psycopg>=3.2`, `psycopg-pool>=3.2`; `psycopg[binary]` only in the dev group.
- Correctness never depends on scheduler clocks: lease expiry and fencing use `now()` in SQL.
- Tests needing PostgreSQL read `GOATBEAT_TEST_DATABASE_URL`; they are skipped when it is unset locally and CI always sets it.

## Review Focus

1. Takeover racing a claim: the fence must take a row lock (`FOR SHARE`) on the lease so a concurrent takeover waits for the claim transaction. Tested with two connections in `test_postgres_store.py`.
2. Timestamp round trips through `timestamptz` keep microseconds and UTC. Conformance suite plus a dedicated test.
3. A lost database connection surfaces as `StoreUnavailableError`, and the scheduler resumes after PostgreSQL returns. `tests/distributed/test_outage.py`.
4. Ten schedulers never double-dispatch. `tests/distributed/test_many_schedulers.py`.
5. Due query uses the partial index at 100,000 schedules. `tests/performance/test_due_query.py`.

---

## Tasks

### Task 1: Package, Docker Compose, test fixtures, CI service
- `packages/goatbeat-postgres` (module `goatbeat.postgres`), `.typecheck` symlink, release config entry, workspace dev deps (`goatbeat-postgres`, `psycopg[binary]`).
- `docker-compose.yml` with `postgres:17` on `localhost:55432`, user/password/db `goatbeat`.
- `tests/postgres_support.py`: `database_url()`; fixture creating an isolated schema per test (`CREATE SCHEMA`, `search_path` in the pool `kwargs.options`), dropped afterwards.
- CI: `postgres:17` service in the test job and `GOATBEAT_TEST_DATABASE_URL`; separate `distributed` job.
- Commit `build: add goatbeat-postgres package and database test harness`.

### Task 2: Schema, migrations, providers
**Produces:** `Cursor`, `ConnectionProvider` protocols (`transaction() -> AbstractContextManager[Cursor]`); `PsycopgProvider(pool)`; `SCHEMA_VERSION`, `migrate(provider) -> int` (idempotent, versioned in `goatbeat_schema_version`), `schema_statements()`.
- Tests: migrate twice is a no-op; tables and the partial index exist; a failing statement rolls back.
- Commit `feat(postgres): add schema migrations and connection providers`.

### Task 3: PostgresStore
**Produces:** `PostgresStore(provider, *, notifier=None, logger=None)` implementing `ScheduleStore` and `LeaseManager`; connection errors raised as `StoreUnavailableError`.
- Tests: `TestPostgresStore(StoreConformance)`; two-connection race where a takeover waits for an open claim transaction; microsecond round trip; undecodable row skipped.
- Commit `feat(postgres): add PostgreSQL store and fenced lease`.

### Task 4: LISTEN/NOTIFY
**Produces:** `PsycopgNotifier(conninfo)` with `wait(timeout) -> bool`; the store notifies `goatbeat_schedule_changed` in the same transaction as schedule writes.
- Tests: a save on one store wakes `wait_for_change` on another within 1 s; timeout returns False.
- Commit `feat(postgres): wake schedulers with LISTEN/NOTIFY`.

### Task 5: Distributed and failure tests
- `tests/distributed/worker.py`: a scheduler process with a submitter that inserts into `dispatch_log`.
- Tests: 10 processes over ~8 s of 1 s schedules, zero duplicate keys and no missing occurrence; SIGKILL the leader and measure failover under `ttl + renew + 2 s`; concurrent claims from 10 threads create one row; submitter failure retried then dispatched; PostgreSQL stop/start (docker compose) with dispatch resuming.
- Commit `test(postgres): add distributed and failure-injection tests`.

### Task 6: Performance
- `tests/performance/test_due_query.py`: bulk insert 100,000 schedules (1,000,000 with `GOATBEAT_PERF_FULL=1`), `EXPLAIN` of the due query uses `goatbeat_schedule_due`, tick over a 500 batch timed.
- Commit `test(postgres): add due-query performance benchmarks`.

### Task 7: Facade, README
- Facade extra `postgres`, README section on production setup.
- Commit `feat: expose the PostgreSQL backend from the facade`.
