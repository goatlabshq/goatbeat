# Phase 4: backends, CLI and observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Celery, Dramatiq and RQ submitters, the standalone `goatbeat` command line, and Prometheus and OpenTelemetry metrics sinks.

**Architecture:** Each backend is its own distribution implementing `TaskSubmitter`, passing the idempotency key as the backend message id (RQ gets a SHA-256 of it because it only accepts `[A-Za-z0-9_-]`). The CLI loads a `GoatbeatApp` (registry, submitter, optional metrics) from `--app module:attribute`, builds the store from `GOATBEAT_DATABASE_URL` (`postgresql://`, `sqlite:///path`, `memory://`) and delegates to `manage.py goatbeat` when `DJANGO_SETTINGS_MODULE` is set.

**Tech Stack:** celery 5.6, dramatiq 2.2, rq 2.12 with fakeredis, prometheus-client, opentelemetry-api/sdk, argparse.

**Spec:** `docs/superpowers/specs/2026-09-25-goatbeat-design.md` (sections 8, 11, 12).

## Global Constraints

- Core stays stdlib only; backends import their library only in their own package.
- Routing options a backend cannot honor raise `SubmissionError` (not silently ignored).
- CLI exit codes: 0 success, 1 check failed, 2 usage error, 3 configuration error, 4 store unavailable.
- Pyright strict; third-party objects without usable types are reached through narrow protocols.

## Review Focus

1. Resubmitting the same occurrence reuses the same backend message id (idempotency) for all three backends.
2. Unsupported routing (`priority` on RQ, `backend` on Celery, Dramatiq and RQ) is rejected.
3. `goatbeat doctor` exits non-zero when the store is unreachable, a task path does not import, or the database clock drifts.
4. Metrics sinks record every `MetricsSink` call with the expected labels.
5. `goatbeat scheduler` stops cleanly on SIGTERM and releases the lease.

---

## Tasks

1. Core: `GoatbeatApp(registry, submitter, metrics=None)`; `LeaseManager.current() -> LeaseInfo | None` (holder, token, expires_at) in the three stores. Commit `feat(core): describe the current lease and bundle an application`.
2. `goatbeat-celery`: `CelerySubmitter(app)` via `send_task(name, args, kwargs, task_id=key, queue=, priority=)`. Tests with a memory broker. Commit `feat(celery): add the Celery submitter`.
3. `goatbeat-dramatiq`: `DramatiqSubmitter(broker)` resolving the actor, `message_with_options(...).copy(message_id=key, queue_name=...)`, priority as `broker_priority`. Tests with `StubBroker`. Commit `feat(dramatiq): add the Dramatiq submitter`.
4. `goatbeat-rq`: `RQSubmitter(connection)` via `Queue(queue).enqueue(path, args=, kwargs=, job_id=sha256(key))`. Tests with fakeredis. Commit `feat(rq): add the RQ submitter`.
5. `goatbeat-prometheus`: `PrometheusMetrics(registry)`. Commit `feat(prometheus): add the Prometheus metrics sink`.
6. `goatbeat-otel`: `OpenTelemetryMetrics(meter)`. Tests with the SDK in-memory reader. Commit `feat(otel): add the OpenTelemetry metrics sink`.
7. `goatbeat-cli`: `goatbeat [--app M:A] scheduler [--once] [--metrics-port N] | status [--json] | doctor [--json] | schedule list [--json] | schedule run NAME | schedule prune`; store from URL; Django delegation; exit codes. Commit `feat(cli): add the goatbeat command line`.
8. Facade extras, README, CLAUDE.md, release config. Commit `feat: expose backends, CLI and metrics from the facade`.
