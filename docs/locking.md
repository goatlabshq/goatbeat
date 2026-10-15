# Locking

All coordination happens in `goatbeat.postgres.store`, as plain SQL.

## The lease row

`goatbeat_lease(partition, holder_id, fencing_token, expires_at)` holds one row. Acquiring or
renewing is a single statement:

```sql
UPDATE goatbeat_lease
SET fencing_token = fencing_token + (holder_id IS DISTINCT FROM $me)::int,
    holder_id = $me,
    expires_at = now() + $ttl
WHERE partition = 0 AND (expires_at <= now() OR holder_id = $me)
RETURNING fencing_token;
```

No row returned means someone else holds a live lease. The statement runs with
`lock_timeout = 1s`, so a stuck transaction elsewhere cannot block a standby.

## The fenced claim

A claim runs in one transaction:

1. `SELECT ... FROM goatbeat_lease WHERE holder_id = $me AND fencing_token = $token AND
   expires_at > now() FOR SHARE`. If nothing matches, the claim aborts with `LeaseLostError`.
   The `FOR SHARE` lock makes a concurrent takeover wait until this transaction ends.
2. `INSERT INTO goatbeat_execution ... ON CONFLICT (idempotency_key) DO NOTHING`.
3. `UPDATE goatbeat_schedule SET next_run_at = $next WHERE id = $id AND next_run_at = $seen`.

The claim transaction also sets `idle_in_transaction_session_timeout` (10 s): if the leader
freezes while holding the fence, PostgreSQL ends its session and the standbys proceed.

## Why not advisory locks

Session-level advisory locks are tied to a connection. Behind PgBouncer in transaction mode they
are released or shared unpredictably, and they carry no fencing token. Goatbeat only uses
transaction-scoped advisory locks for short critical sections (migrations, schedule writes,
completion bookkeeping).

## Schedule writes

Publishing code schedules and saving schedules take a transaction-scoped advisory lock, so
schedulers starting together cannot both insert the same new name.
