# Architecture

## Responsibilities

```text
Scheduling -> determining what is due -> distributed coordination -> submitting tasks
  (core)            (core + store)              (store)               (submitter)
```

Execution belongs to the task backend. Goatbeat's job ends when the backend accepts the task
(and, for Django Tasks, when the completion signal arrives).

## Components

- **Triggers** compute the next occurrence after an instant (`IntervalTrigger`, `CronTrigger`).
- **Misfire planning** turns "the schedule was due at T, it is now T + 3 h" into claims.
- **The store** (`ScheduleStore`) holds schedules and executions. `PostgresStore` is the
  production one; `SQLiteStore` and `MemoryStore` serve development and tests. All three pass
  the same conformance suite.
- **The lease** (`LeaseManager`) elects the scheduler allowed to claim.
- **The submitter** (`TaskSubmitter`) hands a claimed occurrence to Django Tasks, Celery,
  Dramatiq or RQ.
- **The scheduler loop** ties them together and sleeps until the next useful instant.

`goatbeat-core` sees only these protocols and imports nothing outside the standard library; a
test enforces it. Django, PostgreSQL and the backends are adapters.

## Why each distributed mechanism exists

**A lease, so that one scheduler works at a time.** Without it, every instance would read the
same due schedules and race on them. The lease is a row in PostgreSQL with a holder and an
expiry; whoever holds it claims, the others wait.

**The database clock, so that host clocks cannot break the lease.** Expiry is compared with
PostgreSQL's `now()`, never with the scheduler's clock. A host whose clock drifts cannot steal or
keep a lease it should not have.

**A fencing token, so that a paused leader cannot act on a lost lease.** The token increases
each time the holder changes. Every claim checks, in its own transaction, that the token is still
current. A leader frozen by a GC pause or a VM migration wakes up with a stale token and is
refused.

**A local deadline, so that a leader stops before it can be replaced.** A leader considers its
lease valid for `lease_ttl - lease_renew_interval` (20 s by default) after it asked for it,
measured on a monotonic clock. It stops dispatching before another node could take over.

**A unique idempotency key, so that an occurrence cannot be claimed twice.** Even if every other
mechanism failed, the key `schedule_id:scheduled_at` is unique in the executions table. A second
claim inserts nothing.

**Compare-and-set on `next_run_at`, so that concurrent edits win.** A claim advances a schedule
only if nobody changed it meanwhile; an admin edit is never overwritten by a stale claim.

## Guarantees

| Layer | Guarantee |
|---|---|
| Scheduling | each occurrence is claimed at most once |
| Dispatch | at least once: a crash between submission and its bookkeeping resubmits the same key |
| Delivery and execution | those of your backend |
| Business effect | your task's responsibility: make it idempotent |

No backend deduplicates on the key, so a resubmission runs the task twice. Goatbeat never claims
exactly-once execution.
