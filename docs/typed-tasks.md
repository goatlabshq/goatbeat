# Type-safe task definitions

A schedule names a task and, optionally, the arguments it runs with. Goatbeat types both so that
pyright or mypy catch mistakes before deployment.

## Tasks without arguments

Pass the function itself:

```python
beat.schedule(name="cleanup", task=cleanup, every="1h")
```

Goatbeat stores the task by its import path (`myproject.tasks.cleanup`), so the function must be
importable at module level: lambdas and nested functions are rejected.

## Tasks with arguments: `call`

```python
from goatbeat import call


def send_email(user_id: int, *, subject: str = "hello") -> None: ...


beat.schedule(name="welcome", task=call(send_email, 42, subject="hi"), every="1d")
call(send_email, "42")  # type error: str is not int
call(send_email)  # type error: user_id is missing
call(send_email, 1, unknown=1)  # type error: no such parameter
```

`call` uses `ParamSpec`, so its signature is the task's own. Arguments are stored in the
database, so they must be JSON values: strings, numbers, booleans, `None`, lists and string-keyed
dicts. NaN, infinities and NUL characters are rejected because PostgreSQL `jsonb` cannot store
them.

## The declaration itself

`Registry.schedule` has two overloads: one with `cron=` and `timezone=`, one with `every=` and
`start_at=`. Passing both, or neither, is a type error and a runtime `ConfigurationError`.
`misfire_policy` only accepts `"run_once"`, `"skip"`, `"catch_up"` or a `MisfirePolicy`.

## Django Tasks

`goatbeat.django.call` is typed on `django.tasks.Task[P, R]`, so the same checks apply to
`@task` functions. `DjangoRegistry.schedule` accepts a zero-argument `Task` or the result of
`call`; passing a task that needs arguments without `call` is a type error.

## Celery, Dramatiq and RQ

RQ takes plain functions, so `task=send_email` and `call(send_email, 42)` work as shown above.
Celery and Dramatiq wrap functions in objects whose import path is not the name their workers
know, so name the task explicitly with `TaskCall`:

```python
from goatbeat import TaskCall

beat.schedule(name="ping", task=TaskCall("myproject.tasks.ping", (42,)), every="5m")
```

For Celery the path is the registered task name (`myproject.tasks.ping` unless the task sets
`name=`); for Dramatiq it is the module attribute holding the actor. `goatbeat doctor` fails when
a path does not import, so run it before deploying.

## String paths

Only the admin and the `django-celery-beat` importer create schedules from strings. The admin
only accepts `django.tasks.Task` paths; the importer imports other paths disabled, with a note.
