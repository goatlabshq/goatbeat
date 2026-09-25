# Goatbeat

uv workspace of independently published packages sharing the `goatbeat` import namespace.
The design lives in `docs/superpowers/specs/2026-09-25-goatbeat-design.md`.

## Layout

- `packages/goatbeat-core`: framework-agnostic scheduler. Runtime imports are stdlib only; it
  must never import `django`, `celery`, `dramatiq`, `rq`, `psycopg`, `prometheus_client` or
  `opentelemetry` (`tests/test_boundaries.py` enforces it).
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
- Internal dependency pins and versions carry `# x-release-please-version`; release-please
  (`release/`) bumps them all together. Add new packages to `release/config.json`.

## Commands

```bash
uv sync
uv run pytest
uv run pyright
uv run ruff check . && uv run ruff format --check .
```
