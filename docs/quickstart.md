# Quickstart

## Plain Python

```bash
pip install "goatbeat[postgres,rq]"
```

Declare schedules next to your tasks:

```python
# myproject/beat.py
from redis import Redis

from goatbeat import GoatbeatApp, Registry, call
from goatbeat.rq import RQSubmitter
from myproject.tasks import generate_report, send_email

beat = Registry(timezone="America/New_York")
beat.schedule(name="daily-report", task=generate_report, cron="0 9 * * *")
beat.schedule(name="ping", task=call(send_email, 42), every="5m")

app = GoatbeatApp(registry=beat, submitter=RQSubmitter(Redis()))
```

Create the schema and start a scheduler:

```bash
export GOATBEAT_DATABASE_URL=postgresql://goatbeat@localhost/goatbeat
goatbeat --app myproject.beat:app migrate
goatbeat --app myproject.beat:app scheduler
```

Start as many schedulers as you like, on as many hosts: exactly one leads at a time. Check the
setup with `goatbeat --app myproject.beat:app doctor`.

For local experiments, `GOATBEAT_DATABASE_URL=sqlite:///beat.db` and the in-process
`CallableSubmitter` need no services at all. They are not meant for production.

## Django

```bash
pip install "goatbeat[django]"
```

```python
# settings.py
INSTALLED_APPS = [..., "goatbeat.django"]
```

```python
# myapp/schedules.py
from goatbeat.django import DjangoRegistry, call
from myapp.tasks import generate_report, send_email  # django.tasks.Task objects


def register(beat: DjangoRegistry) -> None:
    beat.schedule(name="daily-report", task=generate_report, cron="0 9 * * *")
    beat.schedule(name="ping", task=call(send_email, 42), every="5m")
```

```bash
python manage.py migrate
python manage.py goatbeat scheduler
```

The [Django integration](django.md) page covers settings, the admin and the command.
