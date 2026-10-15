"""Type-checked against the installed wheels in CI: every public name must be exported."""

from datetime import timedelta

from goatbeat import (
    CallableSubmitter,
    ExecutionStatus,
    GoatbeatApp,
    GoatbeatConfig,
    GoatbeatError,
    MemoryStore,
    MisfirePolicy,
    Registry,
    Scheduler,
    SQLiteStore,
    TaskCall,
    call,
)
from goatbeat.celery import CelerySubmitter
from goatbeat.cli.main import main
from goatbeat.core.time import SystemClock
from goatbeat.django import DjangoRegistry, registry
from goatbeat.dramatiq import DramatiqSubmitter
from goatbeat.otel import OpenTelemetryMetrics
from goatbeat.postgres.notify import PsycopgNotifier
from goatbeat.postgres.provider import PsycopgProvider
from goatbeat.postgres.schema import migrate
from goatbeat.postgres.store import PostgresStore
from goatbeat.prometheus import PrometheusMetrics
from goatbeat.rq import RQSubmitter, job_id_for


def send_report(recipient: str, *, urgent: bool = False) -> None:
    print(recipient, urgent)


beat = Registry(timezone="UTC")


def heartbeat() -> None:
    print("alive")


report = call(send_report, "ops@example.com", urgent=True)
beat.schedule(name="report", task=report, cron="0 9 * * 1")
beat.schedule(
    name="heartbeat",
    task=heartbeat,
    every=timedelta(minutes=5),
    misfire_policy=MisfirePolicy.SKIP,
    queue="default",
)
app = GoatbeatApp(registry=beat, submitter=CallableSubmitter())
store = MemoryStore(SystemClock())
scheduler = Scheduler(
    store=store, leases=store, submitter=app.submitter, config=GoatbeatConfig(), registry=beat
)
is_leader: bool = scheduler.is_leader
status: ExecutionStatus = ExecutionStatus.DISPATCHED
task: TaskCall = call(send_report, "dev@example.com")
error: type[Exception] = GoatbeatError
print(is_leader, status, task, error, main, SQLiteStore)
print(PostgresStore, PsycopgProvider, PsycopgNotifier, migrate)
print(DjangoRegistry, registry, CelerySubmitter, DramatiqSubmitter, RQSubmitter, job_id_for)
print(PrometheusMetrics, OpenTelemetryMetrics)
