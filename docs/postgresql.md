# PostgreSQL setup

PostgreSQL 16 or newer. Goatbeat uses four tables (`goatbeat_schedule`, `goatbeat_execution`,
`goatbeat_early_completion`, `goatbeat_lease`) and a version table.

## Schema

- Plain Python: `goatbeat --app ... migrate`. Migrations are versioned and serialized by an
  advisory lock, so concurrent runs are safe. A release refuses to run against a schema newer
  than it knows.
- Django: `python manage.py migrate`.

`goatbeat doctor` reports a schema that is missing, behind or ahead.

## Connection string

`GOATBEAT_DATABASE_URL=postgresql://user:password@host:5432/dbname`, or a libpq keyword string.
Goatbeat adds a connect timeout and TCP keepalives unless you set them.

Each scheduler uses a small pool (up to 4 connections) plus one dedicated connection for
`LISTEN`.

## Poolers

PgBouncer in **transaction** mode works for the store: Goatbeat uses no session state between
transactions. The `LISTEN` connection must reach PostgreSQL directly (or a session-mode pool);
without it, schedulers fall back to polling every `max_sleep`.

## Permissions

The scheduler role needs `SELECT`, `INSERT`, `UPDATE` and `DELETE` on the Goatbeat tables. Only
`migrate` needs `CREATE`. See [security](security.md).

## Maintenance

Execution history grows with every occurrence. Archive or delete old rows of
`goatbeat_execution` on your own schedule; Goatbeat only reads recent ones.
