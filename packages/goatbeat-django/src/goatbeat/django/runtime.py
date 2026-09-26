"""Assembles a scheduler from the Django settings."""

import logging
import socket
from collections.abc import Generator
from contextlib import contextmanager

from goatbeat.core.ids import SchedulerId
from goatbeat.core.scheduler import Scheduler
from goatbeat.django import registry
from goatbeat.django.conf import DjangoSettings
from goatbeat.django.provider import DjangoProvider, notifier_conninfo
from goatbeat.django.submitter import DjangoTasksSubmitter
from goatbeat.postgres.notify import PsycopgNotifier
from goatbeat.postgres.store import PostgresStore


def store(settings: DjangoSettings | None = None) -> PostgresStore:
    loaded = settings or DjangoSettings.from_django()
    return PostgresStore(DjangoProvider(loaded.database))


def cli_requester() -> SchedulerId:
    return SchedulerId(f"cli:{socket.gethostname()}")


@contextmanager
def scheduler(logger: logging.Logger | None = None) -> Generator[Scheduler]:
    settings = DjangoSettings.from_django()
    with PsycopgNotifier(notifier_conninfo(settings.database)) as notifier:
        backend = PostgresStore(DjangoProvider(settings.database), notifier=notifier)
        yield Scheduler(
            store=backend,
            leases=backend,
            submitter=DjangoTasksSubmitter(),
            config=settings.config,
            registry=registry(),
            logger=logger,
        )
