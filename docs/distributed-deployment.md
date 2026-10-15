# Distributed deployment

```text
                     PostgreSQL
                          |
                  Distributed leases
                          |
        +-----------------+-----------------+
        v                 v                 v
 Goatbeat #1        Goatbeat #2        Goatbeat #3
   LEADER             STANDBY             STANDBY
        |
        v
                  Task backend
                        |
             +----------+----------+
             v          v          v
          Worker      Worker      Worker
         Server A    Server B    Server C
```

The same architecture covers one scheduler and one worker on a single machine, or three
schedulers and a hundred workers: only the process counts change.

## Checklist

1. One PostgreSQL database reachable by every scheduler (see [PostgreSQL setup](postgresql.md)).
2. `goatbeat migrate` (or `manage.py migrate`) once per release.
3. Two or three scheduler processes on different hosts, each with the same code version.
4. Workers for your task backend, consuming every routed queue.
5. Metrics and logs collected from every scheduler (see [observability](observability.md)).

## Rolling deployments

Deploy schedulers one at a time. A stopping leader releases its lease, a standby takes over, and
the new version publishes its schedules when it starts. Removed code schedules stay enabled
until `schedule prune` runs with the new code.

## Network partitions

A scheduler cut off from PostgreSQL stops dispatching when its local deadline passes, before
another instance can acquire the lease. With the standalone command, connections use TCP keepalives so
a half-open connection is noticed in about a minute; in Django, set `keepalives` in `OPTIONS`.
