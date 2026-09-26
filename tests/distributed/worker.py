"""A scheduler process for distributed tests: it logs every dispatch into ``dispatch_log``.

Usage: python worker.py CONNINFO SCHEDULER_ID
"""

import logging
import signal
import sys
import threading
from datetime import timedelta
from types import FrameType

import psycopg

from goatbeat.core.config import GoatbeatConfig
from goatbeat.core.execution import SubmissionReceipt
from goatbeat.core.ids import SchedulerId
from goatbeat.core.registry import Registry
from goatbeat.core.scheduler import Scheduler
from goatbeat.core.submission import TaskSubmission
from goatbeat.postgres.notify import PsycopgNotifier
from goatbeat.postgres.provider import PsycopgProvider
from goatbeat.postgres.store import PostgresStore

SCHEDULES = ("every-second-a", "every-second-b")


def noop() -> None: ...


class LoggingSubmitter:
    def __init__(self, conninfo: str, scheduler_id: str) -> None:
        self._conninfo = conninfo
        self._scheduler_id = scheduler_id

    def submit(self, submission: TaskSubmission) -> SubmissionReceipt:
        with psycopg.connect(self._conninfo, autocommit=True) as connection:
            connection.execute(
                "INSERT INTO dispatch_log (idempotency_key, schedule_name, scheduled_at, "
                "scheduler_id) VALUES (%s, %s, %s, %s)",
                [
                    submission.idempotency_key.value,
                    submission.schedule_name,
                    submission.scheduled_at.datetime,
                    self._scheduler_id,
                ],
            )
        return SubmissionReceipt(submission.idempotency_key.value)


def main() -> None:
    conninfo, scheduler_id = sys.argv[1], sys.argv[2]
    logging.basicConfig(level=logging.WARNING)
    registry = Registry()
    for name in SCHEDULES:
        registry.schedule(name=name, task=noop, every="1s")
    stop = threading.Event()

    def terminate(signum: int, frame: FrameType | None) -> None:
        del signum, frame
        stop.set()

    signal.signal(signal.SIGTERM, terminate)
    config = GoatbeatConfig(
        scheduler_id=SchedulerId(scheduler_id),
        lease_ttl=timedelta(seconds=5),
        lease_renew_interval=timedelta(seconds=1),
        max_sleep=timedelta(seconds=1),
    )
    with (
        PsycopgProvider.connect(f"{conninfo} connect_timeout=2") as provider,
        PsycopgNotifier(conninfo) as notifier,
    ):
        store = PostgresStore(provider, notifier=notifier)
        Scheduler(
            store=store,
            leases=store,
            submitter=LoggingSubmitter(conninfo, scheduler_id),
            config=config,
            registry=registry,
        ).run(stop)


if __name__ == "__main__":
    main()
