# Failover

## When the leader dies

A crashed or killed leader stops renewing. Once `expires_at` passes (at most `lease_ttl`, 30 s by
default), the next standby to try acquires the lease with a higher fencing token and starts
claiming. Standbys try at every renewal interval (10 s), so failover takes at most
`lease_ttl + lease_renew_interval`. The distributed test suite kills a real leader process and
measures it.

A leader that stops cleanly (SIGTERM, a deployment) releases the lease on the way out: a standby
takes over at its next attempt.

## Occurrences in flight

An occurrence claimed but not yet recorded as dispatched stays `claimed`. The next leader
resubmits `claimed` rows older than the lease TTL, with the same idempotency key. If the previous
leader had in fact submitted it, the task runs twice: that is the at-least-once window.

## When the leader is only paused

A leader frozen by a GC pause or a VM snapshot may wake up after a standby took over. It cannot
do damage:

- its local deadline (`lease_ttl - lease_renew_interval`) has passed, so it stops dispatching;
- any claim it attempts carries a stale fencing token and is refused by the database;
- if it froze inside a claim transaction, PostgreSQL ended that session after 10 s.

## When PostgreSQL is down

Every scheduler stops dispatching: no lease can be renewed. They retry with exponential backoff
at every renewal interval and resume once the database is back. No occurrence is claimed twice;
an occurrence submitted just before the outage but not yet recorded is resubmitted with the same
key (the at-least-once window). Missed occurrences follow the [misfire policy](misfire.md).

## When the task backend is down

Submissions fail and executions become `submit_failed`, retried with backoff (5 s doubling, at
most 5 minutes) up to `max_submit_retries`, then `failed`.
