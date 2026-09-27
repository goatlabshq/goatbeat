"""The sub-commands; each returns a process exit code."""

import json
import signal
import socket
import sys
import threading
import uuid
from collections.abc import Sequence
from types import FrameType
from typing import Final

from goatbeat.cli import environment as runtime
from goatbeat.cli.environment import Check, Environment
from goatbeat.core.ids import IdempotencyKey, SchedulerId
from goatbeat.core.schedule import Schedule
from goatbeat.core.scheduler import Scheduler
from goatbeat.core.time import SystemClock
from goatbeat.core.triggers import CronTrigger

SUCCESS: Final = 0
CHECK_FAILED: Final = 1
STOP_SIGNALS: Final = (signal.SIGTERM, signal.SIGINT)


class CommandFailedError(Exception):
    """An expected failure reported to the user with exit code 1."""


def run_scheduler(environment: Environment, *, once: bool, metrics_port: int | None) -> int:
    metrics = environment.metrics
    if metrics_port is not None:
        metrics = runtime.prometheus_metrics()
        runtime.start_http_server(metrics_port)
    scheduler = Scheduler(
        store=environment.store,
        leases=environment.leases,
        submitter=environment.submitter,
        config=environment.config,
        registry=environment.registry,
        metrics=metrics,
    )
    if once:
        scheduler.start()
        scheduler.tick()
        return SUCCESS
    stop = threading.Event()

    def request_stop(signum: int, frame: FrameType | None) -> None:
        del signum, frame
        stop.set()

    for stop_signal in STOP_SIGNALS:
        signal.signal(stop_signal, request_stop)
    scheduler.run(stop)
    return SUCCESS


def publish(environment: Environment) -> None:
    """Code-declared schedules must be in the store before anything reads it."""
    environment.store.sync_code_schedules(environment.registry.definitions(), SystemClock().now())


def status(environment: Environment, *, as_json: bool) -> int:
    publish(environment)
    now = SystemClock().now()
    lease = environment.leases.current()
    schedules = environment.store.list_schedules()
    wakeup = environment.store.next_wakeup()
    report: dict[str, object] = {
        "leader": None
        if lease is None
        else {
            "holder": lease.holder.value,
            "token": lease.token.value,
            "expires_at": lease.expires_at.isoformat(),
            "held": lease.held_at(now),
        },
        "schedules": {
            "total": len(schedules),
            "enabled": sum(schedule.definition.enabled for schedule in schedules),
        },
        "next_wakeup": None if wakeup is None else wakeup.isoformat(),
    }
    if as_json:
        _write(json.dumps(report))
        return SUCCESS
    leader = report["leader"]
    _write(f"leader: {leader if leader is not None else 'none yet'}")
    _write(f"schedules: {report['schedules']}")
    _write(f"next wakeup: {report['next_wakeup']}")
    return SUCCESS


def doctor(environment: Environment, *, as_json: bool) -> int:
    checks = _run_checks(environment)
    if as_json:
        _write(json.dumps([_check_dict(check) for check in checks]))
    else:
        for check in checks:
            _write(f"{'ok  ' if check.ok else 'FAIL'} {check.name}: {check.detail}")
    return SUCCESS if all(check.ok for check in checks) else CHECK_FAILED


def list_schedules(environment: Environment, *, as_json: bool) -> int:
    publish(environment)
    described = [_describe(schedule) for schedule in environment.store.list_schedules()]
    if as_json:
        _write(json.dumps(described))
        return SUCCESS
    for item in described:
        state = "enabled" if item["enabled"] else "disabled"
        _write(
            f"{item['name']:<40} {item['source']:<6} {state:<9} "
            f"{item['next_run_at']:<33} {item['trigger']}"
        )
    return SUCCESS


def run_now(environment: Environment, name: str) -> int:
    publish(environment)
    schedule = environment.store.get_schedule(name)
    if schedule is None:
        raise CommandFailedError(f"unknown schedule {name!r}")
    key = IdempotencyKey(f"manual:{uuid.uuid4().hex}")
    requester = SchedulerId(f"cli:{socket.gethostname()}")
    execution = environment.store.request_run(schedule, key, requester, SystemClock().now())
    _write(f"{execution.idempotency_key.value} {execution.status.value}")
    return SUCCESS


def prune(environment: Environment) -> int:
    environment.store.sync_code_schedules(
        environment.registry.definitions(), SystemClock().now(), prune=True
    )
    return SUCCESS


def migrate(environment: Environment) -> int:
    _write(environment.migrate() if environment.migrate else "nothing to migrate")
    return SUCCESS


def _run_checks(environment: Environment) -> Sequence[Check]:
    backend = list(environment.backend_checks())
    if any(not check.ok for check in backend if check.name == "schema"):
        return [Check("store", ok=True, detail="reachable"), *backend]
    publish(environment)
    schedules = environment.store.list_schedules()
    checks = [Check("store", ok=True, detail=f"{len(schedules)} schedules readable")]
    missing = sorted(
        {
            s.definition.task.path
            for s in schedules
            if not environment.task_exists(s.definition.task.path)
        }
    )
    checks.append(
        Check(
            "tasks",
            ok=not missing,
            detail="every task imports" if not missing else f"cannot import: {', '.join(missing)}",
        )
    )
    return [*checks, *backend]


def _check_dict(check: Check) -> dict[str, object]:
    return {"name": check.name, "ok": check.ok, "detail": check.detail}


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


def _write(line: str) -> None:
    sys.stdout.write(f"{line}\n")
