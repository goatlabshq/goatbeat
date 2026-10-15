import json
import signal
import threading
import uuid
from argparse import ArgumentParser
from types import FrameType
from typing import Final, override

from django.core.management import BaseCommand, CommandError
from django.db import ProgrammingError, connection

from goatbeat.core.errors import ConfigurationError
from goatbeat.core.ids import IdempotencyKey
from goatbeat.core.schedule import Schedule
from goatbeat.core.time import SystemClock
from goatbeat.core.triggers import CronTrigger
from goatbeat.django import registry
from goatbeat.django.celery_beat import LEGACY_QUERY, convert, read_legacy
from goatbeat.django.runtime import cli_requester, scheduler, store
from goatbeat.django.submitter import is_django_task, routing_problem

STOP_SIGNALS: Final = (signal.SIGTERM, signal.SIGINT)


class Command(BaseCommand):
    help = "Run the Goatbeat scheduler or manage schedules."

    @override
    def add_arguments(self, parser: ArgumentParser) -> None:
        commands = parser.add_subparsers(dest="command", required=True)
        run = commands.add_parser("scheduler", help="run the scheduler until SIGTERM")
        run.add_argument("--once", action="store_true", help="run a single tick and exit")
        schedules = commands.add_parser("schedule", help="inspect and manage schedules")
        actions = schedules.add_subparsers(dest="action", required=True)
        listing = actions.add_parser("list", help="publish code schedules and list them")
        listing.add_argument("--json", action="store_true", help="machine-readable output")
        run_now = actions.add_parser("run", help="ask the leader to run a schedule now")
        run_now.add_argument("name")
        actions.add_parser("prune", help="disable code schedules no longer declared")
        importer = commands.add_parser(
            "import_celery_beat", help="copy django-celery-beat periodic tasks into Goatbeat"
        )
        importer.add_argument("--dry-run", action="store_true", help="report without writing")

    @override
    def handle(self, *args: object, **options: object) -> None:
        del args
        if options["command"] == "scheduler":
            self._scheduler(once=bool(options["once"]))
        elif options["command"] == "import_celery_beat":
            self._import_celery_beat(dry_run=bool(options["dry_run"]))
        elif options["action"] == "list":
            self._list(as_json=bool(options["json"]))
        elif options["action"] == "run":
            self._run(str(options["name"]))
        else:
            self._prune()

    def _scheduler(self, *, once: bool) -> None:
        with scheduler() as running:
            if once:
                running.start()
                running.tick()
                return
            stop = threading.Event()

            def request_stop(signum: int, frame: FrameType | None) -> None:
                del signum, frame
                stop.set()

            for stop_signal in STOP_SIGNALS:
                signal.signal(stop_signal, request_stop)
            running.run(stop)

    def _list(self, *, as_json: bool) -> None:
        backend = store()
        backend.sync_code_schedules(registry().definitions(), SystemClock().now())
        schedules = backend.list_schedules()
        if as_json:
            self.stdout.write(json.dumps([_describe(schedule) for schedule in schedules]))
            return
        for schedule in schedules:
            item = _describe(schedule)
            state = "enabled" if item["enabled"] else "disabled"
            self.stdout.write(
                f"{item['name']:<40} {item['source']:<6} {state:<9} "
                f"{item['next_run_at']:<33} {item['trigger']}"
            )

    def _run(self, name: str) -> None:
        backend = store()
        schedule = backend.get_schedule(name)
        if schedule is None:
            raise CommandError(f"unknown schedule {name!r}")
        key = IdempotencyKey(f"manual:{uuid.uuid4().hex}")
        execution = backend.request_run(schedule, key, cli_requester(), SystemClock().now())
        self.stdout.write(f"{execution.idempotency_key.value} {execution.status.value}")

    def _import_celery_beat(self, *, dry_run: bool) -> None:
        try:
            with connection.cursor() as cursor:
                cursor.execute(LEGACY_QUERY)
                legacy = read_legacy(cursor.fetchall())
        except ProgrammingError as error:
            raise CommandError(f"cannot read the django_celery_beat tables: {error}") from error
        backend = store()
        now = SystemClock().now()
        for task in legacy:
            result = convert(task, task_exists=is_django_task, routing_problem=routing_problem)
            notes = "; ".join(result.notes)
            if result.definition is None:
                self.stdout.write(f"skipped {task.name}: {notes}")
                continue
            if backend.get_schedule(task.name) is not None:
                self.stdout.write(f"skipped {task.name}: a Goatbeat schedule has this name")
                continue
            if not dry_run:
                try:
                    backend.save_schedule(result.definition, now)
                except ConfigurationError as error:
                    self.stdout.write(f"skipped {task.name}: {error}")
                    continue
            verb = "would import" if dry_run else "imported"
            self.stdout.write(f"{verb} {task.name}" + (f" ({notes})" if notes else ""))

    def _prune(self) -> None:
        try:
            store().sync_code_schedules(registry().definitions(), SystemClock().now(), prune=True)
        except ConfigurationError as error:
            raise CommandError(str(error)) from error


def _describe(schedule: Schedule) -> dict[str, str | bool]:
    trigger = schedule.definition.trigger
    if isinstance(trigger, CronTrigger):
        described = f"cron {trigger.expression.text} ({trigger.timezone.key})"
    else:
        described = f"every {trigger.every}"
    return {
        "name": schedule.name,
        "source": schedule.source.value,
        "enabled": schedule.definition.enabled,
        "next_run_at": schedule.next_run_at.isoformat(),
        "trigger": described,
    }
