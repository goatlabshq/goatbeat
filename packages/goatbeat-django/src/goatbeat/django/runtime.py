import logging
import socket
from collections.abc import Generator
from contextlib import contextmanager
from typing import cast

from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from goatbeat.core.ids import SchedulerId
from goatbeat.core.protocols import TaskSubmitter
from goatbeat.core.scheduler import Scheduler
from goatbeat.django import registry
from goatbeat.django.conf import SUBMITTER_KEY, DjangoSettings
from goatbeat.django.provider import DjangoProvider, notifier_conninfo
from goatbeat.postgres.notify import PsycopgNotifier
from goatbeat.postgres.store import PostgresStore


def store(settings: DjangoSettings | None = None) -> PostgresStore:
    loaded = settings or DjangoSettings.from_django()
    return PostgresStore(DjangoProvider(loaded.database))


def submitter(settings: DjangoSettings | None = None) -> TaskSubmitter:
    path = (settings or DjangoSettings.from_django()).submitter
    target: object = import_string(path)
    if not _is_submitter(target) and callable(target):
        target = target()
    if not _is_submitter(target):
        raise ImproperlyConfigured(
            f"{SUBMITTER_KEY}: {path!r} is neither a task submitter nor a factory returning one"
        )
    return cast("TaskSubmitter", target)


def _is_submitter(target: object) -> bool:
    return not isinstance(target, type) and callable(getattr(target, "submit", None))


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
            submitter=submitter(settings),
            config=settings.config,
            registry=registry(),
            logger=logger,
        )
