# Migration from django-celery-beat

Goatbeat replaces `celery beat` and its database scheduler. Migration copies your periodic tasks,
then you switch which process schedules them.

## 1. Install and migrate

```bash
pip install "goatbeat[django]" "psycopg[binary]"
```

Add `"goatbeat.django"` to `INSTALLED_APPS` and run `python manage.py migrate`. Keep
`django_celery_beat` installed until the end: the importer reads its tables.

## 2. Preview the import

```bash
python manage.py goatbeat import_celery_beat --dry-run
```

Every `PeriodicTask` is reported as `would import` (with notes) or `skipped` (with the reason).
Run it again without `--dry-run` to write. The import is idempotent: names that already exist in
Goatbeat are skipped.

## 3. What is converted

| django-celery-beat | Goatbeat |
|---|---|
| `IntervalSchedule(every, period)` | `every=` interval, anchored on `start_time` if set |
| `CrontabSchedule` | `cron=` with the crontab's timezone |
| `PeriodicTask.task`, `args`, `kwargs` | task path and JSON arguments |
| `queue`, `priority` | routing, checked against your Django Tasks backend |
| `enabled` | enabled (see below) |
| `SolarSchedule`, `ClockedSchedule` | skipped: no equivalent |
| `one_off`, `expires`, `expire_seconds`, `exchange`, `routing_key`, `headers` | dropped, reported per task |
| `start_time` on a crontab | dropped, reported (Goatbeat runs from the next match) |

Rows are never re-synced: a task edited in django-celery-beat after the import keeps its imported
version. Skipped rows include solar and clocked schedules, crontabs restricting both day of month
and day of week (celery requires both to match, cron either), and syntax cron does not accept
(wrap-around ranges such as `fri-mon`, full day names). A queue or priority your backend refuses
(celery allows priorities up to 255, Django Tasks -100 to 100) is imported disabled with a note.

Interval schedules without `start_time` are anchored on the Unix epoch, not on the last run: an
hourly task runs at minute 0, a weekly one on Thursdays at 00:00 UTC. Set `start_time` in
django-celery-beat before importing if that matters.

Imported schedules are store schedules, editable in the admin. Their misfire policy is
`run_once`, the closest match to celery beat, which also runs a missed task once.

## 4. Port the tasks

Celery task names are not Django tasks. A periodic task whose path is not a
`django.tasks.Task` is imported **disabled**, with a note. Port the function to `@task` under
the same import path (the admin refuses non-Django paths), then enable each schedule.

To keep running the Celery tasks themselves, use `goatbeat-celery` with the standalone command
instead of Django Tasks:

```python
app = GoatbeatApp(registry=beat, submitter=CelerySubmitter(celery_app))
```

## 5. Switch over

1. Stop `celery beat`.
2. Start `python manage.py goatbeat scheduler` (one or more, on any hosts).
3. Watch `goatbeat status` and the admin's execution history.

## Operational differences

- **Concurrency.** celery beat must run exactly once; running two duplicates every task. Goatbeat
  is safe with any number of schedulers.
- **Restarts.** celery beat may run a task again or skip it depending on `last_run_at`. Goatbeat
  claims each occurrence once and applies an explicit [misfire policy](misfire.md).
- **Change detection.** celery beat polls `PeriodicTasks.last_update`; Goatbeat reads due
  schedules through an index and wakes on `LISTEN/NOTIFY`.
- **History.** Every occurrence leaves an execution row with its status, error and retry count.
