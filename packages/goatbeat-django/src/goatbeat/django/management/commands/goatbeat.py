"""``manage.py goatbeat``: run the scheduler and manage schedules."""

import json
import signal
import threading
import uuid
from argparse import ArgumentParser
from types import FrameType
from typing import Final, override

from django.core.management import BaseCommand, CommandError

from goatbeat.core.errors import ConfigurationError
from goatbeat.core.ids import IdempotencyKey
from goatbeat.core.schedule import Schedule
from goatbeat.core.time import SystemClock
from goatbeat.core.triggers import CronTrigger
from goatbeat.django import registry
from goatbeat.django.runtime import cli_requester, scheduler, store

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

    @override
    def handle(self, *args: object, **options: object) -> None:
        del args
        if options["command"] == "scheduler":
            self._scheduler(once=bool(options["once"]))
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
