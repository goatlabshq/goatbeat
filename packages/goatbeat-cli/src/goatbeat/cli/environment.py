import os
from collections.abc import Callable, Generator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import timedelta
from importlib import import_module
from importlib.util import find_spec
from typing import Final
from urllib.parse import urlsplit

from goatbeat.core.app import GoatbeatApp
from goatbeat.core.config import GoatbeatConfig
from goatbeat.core.errors import ConfigurationError
from goatbeat.core.observability import FanoutMetrics, MetricsSink, NoopMetrics
from goatbeat.core.protocols import LeaseManager, ScheduleStore, TaskSubmitter
from goatbeat.core.registry import SupportsDefinitions
from goatbeat.core.stores.memory import MemoryStore
from goatbeat.core.stores.sqlite import SQLiteStore
from goatbeat.core.tasks import import_object
from goatbeat.core.time import SystemClock

APP_VARIABLE: Final = "GOATBEAT_APP"
DJANGO_VARIABLE: Final = "DJANGO_SETTINGS_MODULE"
DATABASE_VARIABLE: Final = "GOATBEAT_DATABASE_URL"
SQLITE_PREFIX: Final = "sqlite:///"
# libpq also accepts "host=... dbname=..." strings; they carry no URL scheme.
LIBPQ_KEYWORDS: Final = "libpq"
# Lease correctness ignores host clocks; a larger drift still confuses logs and schedules.
MAX_CLOCK_DRIFT: Final = timedelta(seconds=2)
PROMETHEUS_HINT: Final = "--metrics-port needs: pip install goatbeat[prometheus]"


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str


def no_checks() -> Sequence[Check]:
    return ()


def always_ready() -> None:
    pass


def import_problem(path: str) -> str | None:
    try:
        import_object(path)
    except Exception as error:
        return f"{path}: {type(error).__name__}: {error}"
    return None


@dataclass(slots=True)
class Environment:
    config: GoatbeatConfig
    store: ScheduleStore
    leases: LeaseManager
    registry: SupportsDefinitions
    submitter: TaskSubmitter
    metrics: MetricsSink
    backend_checks: Callable[[], Sequence[Check]] = no_checks
    migrate: Callable[[], str] | None = None
    task_problem: Callable[[str], str | None] = import_problem
    ready: Callable[[], None] = always_ready


def start_http_server(port: int) -> None:
    try:
        from prometheus_client import start_http_server as serve  # noqa: PLC0415
    except ImportError as error:
        raise ConfigurationError(PROMETHEUS_HINT) from error
    serve(port)


def scheduler_metrics(configured: MetricsSink, port: int | None) -> MetricsSink:
    if port is None:
        return configured
    try:
        from goatbeat.prometheus import PrometheusMetrics  # noqa: PLC0415
    except ImportError as error:
        raise ConfigurationError(PROMETHEUS_HINT) from error
    start_http_server(port)
    if isinstance(configured, PrometheusMetrics):
        return configured
    if isinstance(configured, NoopMetrics):
        return PrometheusMetrics()
    return FanoutMetrics(configured, PrometheusMetrics())


@contextmanager
def open_environment(app_reference: str | None) -> Generator[Environment]:
    reference = app_reference or os.environ.get(APP_VARIABLE)
    with ExitStack() as stack:
        if reference is None and os.environ.get(DJANGO_VARIABLE):
            yield _django_environment(stack)
        elif reference is None:
            raise ConfigurationError(
                "tell goatbeat where your schedules are: --app module:attribute, "
                f"{APP_VARIABLE}, or {DJANGO_VARIABLE} for a Django project"
            )
        else:
            config = GoatbeatConfig.from_env(os.environ)
            yield _standalone_environment(stack, load_app(reference), config)


def load_app(reference: str) -> GoatbeatApp:
    module_name, _, attribute = reference.partition(":")
    if not module_name or not attribute:
        raise ConfigurationError(f"--app expects module:attribute, got {reference!r}")
    try:
        module = import_module(module_name)  # nosemgrep: non-literal-import
        target: object = getattr(module, attribute)
    except (ImportError, AttributeError) as error:
        raise ConfigurationError(f"cannot load {reference!r}: {error}") from error
    if callable(target):
        target = target()
    if not isinstance(target, GoatbeatApp):
        raise ConfigurationError(f"{reference!r} is not a GoatbeatApp")
    return target


def _standalone_environment(
    stack: ExitStack, app: GoatbeatApp, config: GoatbeatConfig
) -> Environment:
    url = config.database_url
    if url is None:
        raise ConfigurationError(
            f"set {DATABASE_VARIABLE} (postgresql://..., {SQLITE_PREFIX}path or memory://)"
        )
    scheme = urlsplit(url).scheme or (LIBPQ_KEYWORDS if "=" in url else "")
    if scheme == "memory":
        memory = MemoryStore(SystemClock())
        return _environment(app, config, memory, memory)
    if scheme == "sqlite":
        sqlite = SQLiteStore(_sqlite_path(url), SystemClock())
        stack.callback(sqlite.close)
        return _environment(app, config, sqlite, sqlite)
    if scheme in {"postgres", "postgresql", LIBPQ_KEYWORDS}:
        return _postgres_environment(stack, app, config, url)
    raise ConfigurationError(f"unsupported database URL scheme {scheme!r}")


def _sqlite_path(url: str) -> str:
    path = url.removeprefix(SQLITE_PREFIX)
    if not url.startswith(SQLITE_PREFIX) or not path or urlsplit(url).netloc:
        raise ConfigurationError(
            f"SQLite URLs look like {SQLITE_PREFIX}relative.db or {SQLITE_PREFIX}/absolute.db, "
            f"got {url!r}"
        )
    return path


def _environment(
    app: GoatbeatApp, config: GoatbeatConfig, store: ScheduleStore, leases: LeaseManager
) -> Environment:
    return Environment(
        config=config,
        store=store,
        leases=leases,
        registry=app.registry,
        submitter=app.submitter,
        metrics=app.metrics,
    )


def _postgres_environment(
    stack: ExitStack, app: GoatbeatApp, config: GoatbeatConfig, url: str
) -> Environment:
    try:
        from goatbeat.postgres.notify import PsycopgNotifier  # noqa: PLC0415
        from goatbeat.postgres.provider import PsycopgProvider  # noqa: PLC0415
        from goatbeat.postgres.schema import (  # noqa: PLC0415
            SCHEMA_VERSION,
            applied_version,
            database_clock,
            migrate,
        )
        from goatbeat.postgres.store import PostgresStore  # noqa: PLC0415
    except ImportError as error:
        raise ConfigurationError("PostgreSQL needs: pip install goatbeat[postgres]") from error
    provider = stack.enter_context(PsycopgProvider.connect(url, wait=True))
    notifier = stack.enter_context(PsycopgNotifier(url))
    store = PostgresStore(provider, notifier=notifier)

    def schema_problem() -> str | None:
        version = applied_version(provider)
        if version < SCHEMA_VERSION:
            return f"schema at version {version}, expected {SCHEMA_VERSION}: run goatbeat migrate"
        if version > SCHEMA_VERSION:
            return f"schema at version {version} is newer than this release: upgrade goatbeat"
        return None

    def ready() -> None:
        problem = schema_problem()
        if problem is not None:
            raise ConfigurationError(problem)

    def checks() -> Sequence[Check]:
        problem = schema_problem()
        drift = database_clock(provider) - SystemClock().now()
        return (
            Check("schema", problem is None, problem or f"at version {SCHEMA_VERSION}"),
            Check(
                "clock",
                abs(drift) <= MAX_CLOCK_DRIFT,
                f"local clock is {drift.total_seconds():+.3f} s from PostgreSQL",
            ),
        )

    def apply_migrations() -> str:
        return f"schema at version {migrate(provider)}"

    environment = _environment(app, config, store, store)
    environment.backend_checks = checks
    environment.migrate = apply_migrations
    environment.ready = ready
    return environment


def _django_environment(stack: ExitStack) -> Environment:
    try:
        import django  # noqa: PLC0415
        from django.core.exceptions import ImproperlyConfigured  # noqa: PLC0415

        from goatbeat.django import registry  # noqa: PLC0415
        from goatbeat.django.conf import DjangoSettings  # noqa: PLC0415
        from goatbeat.django.provider import DjangoProvider, notifier_conninfo  # noqa: PLC0415
        from goatbeat.django.submitter import DjangoTasksSubmitter, is_django_task  # noqa: PLC0415
        from goatbeat.postgres.notify import PsycopgNotifier  # noqa: PLC0415
        from goatbeat.postgres.store import PostgresStore  # noqa: PLC0415
    except ImportError as error:
        raise ConfigurationError("Django projects need: pip install goatbeat[django]") from error
    module = os.environ.get(DJANGO_VARIABLE, "")
    try:
        if find_spec(module) is None:
            raise ImportError(f"no module named {module!r}")
        django.setup()
    except (ImportError, ImproperlyConfigured) as error:
        raise ConfigurationError(f"cannot load the Django settings {module!r}: {error}") from error
    settings = DjangoSettings.from_django()
    notifier = stack.enter_context(PsycopgNotifier(notifier_conninfo(settings.database)))
    store = PostgresStore(DjangoProvider(settings.database), notifier=notifier)
    environment = Environment(
        config=settings.config,
        store=store,
        leases=store,
        registry=registry(),
        submitter=DjangoTasksSubmitter(),
        metrics=NoopMetrics(),
        task_problem=lambda path: None if is_django_task(path) else f"{path}: not a Django task",
    )
    environment.migrate = lambda: "Django projects migrate with: python manage.py migrate"
    return environment
