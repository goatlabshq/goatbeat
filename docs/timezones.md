# Timezones

Inside Goatbeat every instant is an aware UTC datetime. A naive datetime is rejected with
`NaiveDatetimeError`; it is never interpreted in some local zone.

Cron schedules are evaluated in their own timezone: the `timezone=` argument, else the registry
default, else UTC (Django: `TIME_ZONE`).

## Daylight saving time

Goatbeat follows Vixie cron, the behavior most operators already expect.

| Situation | Fixed hour (`30 2 * * *`) | Every hour (`*/30 * * * *`) |
|---|---|---|
| Clocks spring forward, 02:30 does not exist | runs once, at the end of the gap (03:00) | follows real time, the gap is skipped |
| Clocks fall back, 01:30 happens twice | runs once, on the first pass | runs on both passes |

An hour field counts as "every hour" when it matches all 24 hours (`*`, `*/1`, `0-23`).

Gaps at midnight (some zones change at 00:00) and half-hour shifts (Australia/Lord_Howe) follow
the same rules; they are covered by the test suite.

## Changing a schedule's timezone

The next occurrence is recomputed from now in the new zone. No occurrence is created for the
time between the old and the new next run.

## Interval schedules

`every="1d"` is 24 elapsed hours. Across a DST change it shifts by an hour in local time. Use
cron for wall-clock schedules.
