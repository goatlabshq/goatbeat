# Goatbeat

uv workspace of independently published packages sharing the `goatbeat` import namespace.
The design lives in `docs/superpowers/specs/2026-09-25-goatbeat-design.md`.

## Layout

- `packages/goatbeat-core`: framework-agnostic scheduler. Runtime imports are stdlib only; it
  must never import `django`, `celery`, `dramatiq`, `rq`, `psycopg`, `prometheus_client` or
  `opentelemetry` (`tests/test_boundaries.py` enforces it).
- `packages/goatbeat-postgres`: production store. All coordination SQL lives in
  `goatbeat/postgres/store.py`, typed `LiteralString`, behind the `ConnectionProvider` protocol.
- `packages/goatbeat-django`: Django app `goatbeat.django` (label `goatbeat`). It reuses
  `PostgresStore` through `DjangoProvider`; its migrations must keep matching
  `goatbeat.postgres.schema` (`tests/test_schema_equivalence.py`). Admin writes go through the store.
- `packages/goatbeat-{celery,dramatiq,rq}`: one `TaskSubmitter` each; libraries whose types are
  incomplete are reached through narrow private protocols.
- `packages/goatbeat-{prometheus,otel}`: `MetricsSink` implementations.
- `packages/goatbeat-cli`: the `goatbeat` command. It imports backends lazily so optional
  packages stay optional; exit codes 0/1/2/3/4 are part of its contract.
- `packages/goatbeat`: facade distribution. It alone owns `goatbeat/__init__.py`; every other
  package is a namespace portion (`goatbeat/core/`, ...). `pkgutil.extend_path` in that file makes
  editable installs work at runtime.
- `legacy/`: git-ignored django-celery-beat checkout, reference for the migration guide only.

## Rules

- `.typecheck/goatbeat` is a symlink tree merging the facade and every portion. Pyright cannot
  merge a regular package with namespace portions spread over several editable roots, so it
  resolves `goatbeat` through `extraPaths = [".typecheck"]`. Add a symlink there when adding a
  package.
- Every datetime inside core is an `Instant` (aware, UTC). Naive datetimes are rejected, never
  converted.
- Coordination correctness never depends on scheduler clocks: lease expiry uses the store clock.
- django-stubs generics are not subscriptable at runtime: parameterize Django base classes through
  `goatbeat/django/generics.py` and use `from __future__ import annotations` where `Task[...]` appears.
- Internal dependency pins and versions carry `# x-release-please-version`; release-please
  (`release/`) bumps them all together. Add new packages to `release/config.json`.

## Commands

PostgreSQL tests need `docker compose up -d --wait postgres` and
`GOATBEAT_TEST_DATABASE_URL=postgresql://goatbeat:goatbeat@localhost:55432/goatbeat`; without the
variable they are skipped. `-m distributed` and `-m performance` are excluded by default.

```bash
uv sync
uv run pytest
uv run pyright
uv run ruff check . && uv run ruff format --check .
```
