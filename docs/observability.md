# Observability

## Logs

Goatbeat logs to the `goatbeat` logger with a stable event name as the message and structured
fields (`scheduler_id`, `fencing_token`, `schedule`, `idempotency_key`, ...):

| Event | When |
|---|---|
| `scheduler.started`, `scheduler.stopped` | process lifecycle |
| `lease.acquired`, `leader.lost` | leadership changes |
| `occurrence.skipped`, `occurrence.dispatched` | per occurrence |
| `submission.failed` | the backend refused a task (with `retry_count`, `final`) |
| `store.unavailable`, `tick.failed` | database or unexpected errors |
| `schedule.invalid`, `schedule.failed` | a stored schedule cannot be decoded or planned |

The command line prints them on stderr: `--log-format json` emits one JSON object per line,
`--log-level` filters. In your own process, attach `goatbeat.core.observability.JsonFormatter`
to a handler.

## Metrics

Pass a sink to `GoatbeatApp(metrics=...)` or the `Scheduler`.

| Prometheus (`goatbeat-prometheus`) | OpenTelemetry (`goatbeat-otel`) | Meaning |
|---|---|---|
| `goatbeat_leader` | `goatbeat.leader` | 1 while this process leads |
| `goatbeat_leadership_acquired_total` | `goatbeat.leadership.acquired` | leadership acquisitions (failovers) |
| `goatbeat_occurrences_total{status}` | `goatbeat.occurrences{status}` | occurrences by resulting status |
| `goatbeat_dispatch_latency_seconds` | `goatbeat.dispatch.latency` | dispatch time minus scheduled time |
| `goatbeat_tick_duration_seconds` | `goatbeat.tick.duration` | duration of one tick |

`goatbeat scheduler --metrics-port 9464` serves Prometheus metrics; it reuses the app's
Prometheus sink if it has one, or sends to both sinks otherwise.

Useful alerts: `sum(goatbeat_leader) != 1` for more than a minute, a rising
`goatbeat_occurrences_total{status="failed"}`, and dispatch latency above your tolerance.

## Status

`goatbeat status --json` shows the lease holder, its token and expiry, schedule counts and the
next wake-up. The Django admin shows per-schedule history.
