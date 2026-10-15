# Misfire policies

An occurrence is **late** when it is more than `misfire_grace` older than now (60 seconds by
default). Late occurrences happen after an outage, a long deployment, or a schedule re-enabled
after a pause. Occurrences within the grace period always run, whatever the policy.

```python
beat.schedule(
    name="report",
    task=report,
    every="1h",
    misfire_policy="catch_up",
    misfire_grace=timedelta(minutes=5),
    max_catch_up=24,
)
```

## `run_once` (default)

Run only the most recent late occurrence. The others are counted in its `missed_count` (for cron
schedules, a lower bound past 10,000 missed occurrences). After a
three-hour outage, an hourly schedule runs once, with `missed_count=2`.

## `skip`

Run nothing late. One `skipped` execution is recorded for the most recent late occurrence, with
`missed_count` counting the others, so the gap stays visible in the history.

## `catch_up`

Run every late occurrence in order, each with its own idempotency key, up to `max_catch_up`
(100 by default). Older occurrences beyond the cap are recorded as one `skipped` execution.
Planning is bounded: an interval schedule computes the cap arithmetically, so a year of
one-second occurrences plans in milliseconds.

## In every case

`scheduled_at` always holds the theoretical time, never the time of the dispatch, so tasks can
tell which occurrence they serve. Re-enabling a disabled schedule restarts it from now: a
schedule paused for a week does not flood the backend when it comes back.
