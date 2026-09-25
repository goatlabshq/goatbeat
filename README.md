# Goatbeat

A type-safe, distributed periodic task scheduler for Python, with first-class support for
Django 6.1 Tasks.

> Schedule once. Dispatch reliably. Scale everywhere.

Goatbeat decides what is due, coordinates several scheduler instances through a fenced lease,
claims each occurrence exactly once and submits it to your task backend. Execution stays the
job of Django Tasks, Celery, Dramatiq or RQ.

Status: under active development. See the
[design](docs/superpowers/specs/2026-09-25-goatbeat-design.md).

## Development

```bash
uv sync
uv run pytest
uv run pyright
uv run ruff check . && uv run ruff format --check .
```
