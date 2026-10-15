# Performance

The scheduler never loads the whole schedule table. Due schedules come from a partial index:

```sql
CREATE INDEX goatbeat_schedule_due ON goatbeat_schedule (next_run_at) WHERE enabled;
SELECT ... WHERE enabled AND next_run_at <= $now ORDER BY next_run_at LIMIT 500;
```

Measured by `tests/performance` on a laptop with PostgreSQL 17:

| Schedules | Due query (500 rows) | One tick (claim and submit 500) |
|---|---|---|
| 100,000 | 5.3 ms | 0.55 s |
| 1,000,000 | 5.2 ms | 0.66 s |

The query plan uses the partial index with no sequential scan at either size; the test asserts
it. Run them with:

```bash
uv run pytest -m performance tests/performance            # 100,000 schedules
GOATBEAT_PERF_FULL=1 uv run pytest -m performance tests/performance
```

## Tuning

- `batch_size` (500): larger batches mean fewer queries per tick for bursts of due schedules.
- `max_sleep` (60 s): only matters without `LISTEN/NOTIFY`, as a polling bound.
- Cron evaluation costs a few microseconds per occurrence; misfire planning of long outages is
  bounded (see [misfire policies](misfire.md)).
- Submission speed is your broker's: the tick submits occurrences one by one.
