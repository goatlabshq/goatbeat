# Scheduling

Every schedule has one trigger. A trigger answers a single question: given an instant, when is
the next occurrence strictly after it?

## Intervals

```python
beat.schedule(name="ping", task=ping, every="30s")  # also "5m", "1h", "1d" or a timedelta
```

Occurrences fall on `start_at + k * every`. The default `start_at` is the Unix epoch, so a
schedule keeps the same grid across restarts and deployments, and delays never accumulate:
a tick that runs late does not push the next occurrence back.

`every` is elapsed time. `"1d"` is exactly 24 hours whatever the timezone; use a cron schedule
for "every day at 09:00 local time".

## Cron

```python
beat.schedule(name="report", task=report, cron="0 9 * * 1-5", timezone="Europe/Paris")
```

Five fields: minute, hour, day of month, month, day of week. Lists (`1,15`), ranges (`1-5`),
steps (`*/15`, `10-50/10`) and names (`jan`, `mon-fri`) are supported; `0` and `7` both mean
Sunday. When both day fields are restricted, a day matches if either matches, as in POSIX cron.

Expressions that can never match, such as `0 0 30 2 *`, are rejected when declared. Rare but valid
ones, such as February 29 falling on a Sunday, are found: the search covers the whole 400-year
Gregorian cycle.

Cron schedules are evaluated in their own timezone; see [timezones](timezones.md) for daylight
saving rules.

## What happens at each tick

1. The leader reads the schedules whose `next_run_at` is due, oldest first, 500 at a time.
2. For each, the [misfire policy](misfire.md) decides which occurrences to run.
3. Each occurrence is claimed (one row, identified by its idempotency key) and the schedule's
   `next_run_at` advances, in the same transaction.
4. Claimed occurrences are submitted to the task backend.
5. The scheduler sleeps until the next useful moment: the next due schedule, the next retry or
   the next lease renewal, at most `max_sleep` (60 s by default). On PostgreSQL a schedule change
   wakes it immediately through `LISTEN/NOTIFY`.

## Execution statuses

| Status | Meaning |
|---|---|
| `requested` | an extra run asked for from the admin or the command line |
| `claimed` | the occurrence is reserved, submission pending |
| `dispatched` | the backend accepted the task |
| `submit_failed` | the backend refused it; a retry is scheduled |
| `failed` | the first submission and `max_submit_retries` retries (5 by default) all failed |
| `skipped` | the misfire policy decided not to run it |
| `completed`, `task_failed` | the task finished (tracked for Django Tasks) |

Submission retries back off exponentially: 5 s, 10 s, 20 s and so on, capped at 5 minutes.

## Code and store schedules

Schedules declared in code are published to the store when a scheduler starts (and by the
command line). Schedules created in the Django admin live in the store only. A code schedule
removed from the code stays enabled until you run `schedule prune`, because during a rolling
deployment an old process would otherwise disable schedules the new release just added.
