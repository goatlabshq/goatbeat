# Troubleshooting

Start with `goatbeat doctor` (or `--json`): it checks the store, every task path, the schema
version and the clock drift between the host and PostgreSQL.

**"configuration error: schema at version 0, expected N: run goatbeat migrate"**
: The database has no Goatbeat tables yet, or an older schema. Run the migration.

**"schema at version N is newer than this release: upgrade goatbeat"**
: A newer release migrated the database. Upgrade every scheduler.

**Nothing is dispatched**
: Check `goatbeat status`: is there a leader whose lease is held? Is the schedule enabled? Is
  `next_wakeup` in the future? Look for `schedule.invalid` or `schedule.failed` in the logs.

**Two schedulers both log `lease.acquired`**
: Normal over time (failover). At the same moment it is impossible: they would hold different
  fencing tokens and the older one's claims are refused.

**Executions stay `dispatched`**
: Expected for Celery, Dramatiq and RQ, whose completions Goatbeat does not track. For Django
  Tasks, check that workers load the `goatbeat.django` app so `task_finished` reaches it.

**Executions become `failed`**
: The backend refused the task `max_submit_retries` times. The `error` column says why: unknown
  task, unknown queue, unsupported routing, broker down.

**A task ran twice**
: The at-least-once window: a scheduler crashed after submitting and before recording the
  dispatch, or a broker redelivered. Make the task idempotent with its idempotency key.

**`doctor` reports clock drift**
: Leases do not depend on host clocks, but logs and `status` become confusing. Fix NTP on the
  host.

**`goatbeat` exits with code 5**
: An unexpected error. The message names its type; please report it with the logs.
