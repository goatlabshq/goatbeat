# Multiple scheduler instances

Run as many `goatbeat scheduler` processes as you want, on any hosts, against the same database.
This is the normal deployment, not a special mode.

- Exactly one instance leads at a time; the others are standbys renewing nothing and claiming
  nothing.
- Every instance publishes the code schedules it knows at startup. Run the same code version
  everywhere, or at least only add schedules in new versions: an old process never disables what
  a new one added.
- Any instance, and the admin, can request an extra run (`schedule run`). The request is stored;
  the leader dispatches it.
- Give each instance a distinct `scheduler_id` if you set one explicitly. The default
  (`host:pid:random`) is unique.

## How many

Two or three instances on different hosts give fast failover. More adds nothing: one leader does
all the work, and a tick claims and submits 500 occurrences in well under a second (see
[performance](performance.md)).

## Verified behavior

The distributed test suite starts ten real scheduler processes on one database with
one-second schedules and checks that no occurrence is dispatched twice and none is missed.
