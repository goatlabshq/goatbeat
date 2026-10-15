# Security

## Database

- Use a dedicated role. Schedulers need `SELECT`, `INSERT`, `UPDATE`, `DELETE` on the Goatbeat
  tables; give `CREATE` only to the role that runs migrations.
- All SQL uses bound parameters. Queries are typed `LiteralString`, so the type checker rejects
  any query assembled from runtime values.
- Use TLS (`sslmode=verify-full` in the connection string) when the database is remote.

## Who can run what

A schedule's task path is imported and called by your workers. Anyone who can create schedules
can run any importable task with arguments of their choice. Treat the right to edit schedules
like the right to deploy code:

- The Django admin requires the `change` permission on schedules for every action; view-only
  staff cannot enable, disable or run anything.
- The admin only accepts `django.tasks.Task` paths.
- Restrict write access to the Goatbeat tables.

## Arguments

Task arguments are stored as JSON in the database and in your broker. Do not put secrets in
them; pass an identifier and let the task fetch the secret.

## Secrets in configuration

`GOATBEAT_DATABASE_URL` contains credentials. Provide it through your secret manager, not in
command lines visible to other users.
