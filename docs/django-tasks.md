# Django Tasks integration

Goatbeat does not run tasks. Each due occurrence becomes one `Task.enqueue()` call; your
configured Django Tasks backend and its workers do the rest.

## How an occurrence is submitted

```python
task.using(queue_name=..., priority=..., backend=...).enqueue(*args, **kwargs)
```

Routing comes from the schedule (`queue=`, `priority=`, `backend=`); options left unset keep the
task's own defaults. An unknown queue or backend makes the submission fail and be retried, then
marked `failed`.

## The idempotency key

Each occurrence has a key such as `9f3c...:2026-10-15T09:00:00+00:00`, or `manual:<uuid>` for
extra runs. Django Tasks has no caller-provided id, so a task that wants the key declares a
parameter for it:

```python
@task
def send_report(goatbeat_key: str = "") -> None:
    if already_sent(goatbeat_key):
        return
    ...
```

Declare such a task with `task=call(send_report)`: the extra parameter makes it a task with
arguments for the type checker. Use the key to make the task idempotent: in rare crash windows an
occurrence is submitted twice.

## Completion tracking

Goatbeat listens to `django.tasks.signals.task_finished` and marks the execution `completed` or
`task_failed`. Immediate backends report the outcome during `enqueue`. If a fast worker finishes
before the scheduler recorded the dispatch, the completion is kept for a day and applied when
the dispatch is recorded. Bookkeeping errors are logged and never fail the task.

## Backends

Django 6.1 ships `ImmediateBackend` (runs inline, useful in development) and `DummyBackend`
(stores results, for tests). Production needs a worker backend from a third-party package; any
backend implementing the public Django Tasks API works with Goatbeat.
