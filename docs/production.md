# Production deployment

## Processes

| Process | Count | Command |
|---|---|---|
| scheduler | 2 or 3, on different hosts | `goatbeat --app myproject.beat:app scheduler` or `manage.py goatbeat scheduler` |
| workers | as many as the load needs | your task backend's worker |
| migration | once per release | `goatbeat migrate` or `manage.py migrate` |

Run schedulers under a supervisor (systemd, Kubernetes, ECS). They stop on `SIGTERM`, releasing
the lease, and exit 0.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `GOATBEAT_APP` | | `module:attribute` of the `GoatbeatApp` (or `--app`) |
| `GOATBEAT_DATABASE_URL` | | `postgresql://...` (or `sqlite:///file` for development) |
| `GOATBEAT_SCHEDULER_ID` | `host:pid:random` | name in logs, metrics and the lease |
| `GOATBEAT_TIMEZONE` | `UTC` | default timezone of cron schedules |
| `GOATBEAT_LEASE_TTL` | `30s` | how long a lease lives without renewal |
| `GOATBEAT_LEASE_RENEW_INTERVAL` | `10s` | must be less than half the TTL |
| `GOATBEAT_MAX_SLEEP` | `60s` | longest sleep between ticks |
| `GOATBEAT_BATCH_SIZE` | `500` | due schedules read per query |
| `GOATBEAT_MAX_SUBMIT_RETRIES` | `5` | retries before an execution is `failed` |

Invalid values stop the process at startup with every problem listed.

## Health checks

- Liveness: the process is running.
- Readiness and alerting: `goatbeat doctor --json` (exit 1 on any failed check) and the
  `goatbeat_leader` metric, which must sum to 1 across schedulers.

## Command line exit codes

`0` success, `1` a check failed, `2` usage error, `3` configuration error, `4` store
unavailable, `5` unexpected error.

## Upgrades

1. Run the new release's migration.
2. Restart schedulers one at a time.
3. Run `schedule prune` with the new code if schedules were removed.
