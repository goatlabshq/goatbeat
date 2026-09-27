"""A MetricsSink recording through the OpenTelemetry metrics API."""

from opentelemetry.metrics import Meter

from goatbeat.core.execution import ExecutionStatus


class OpenTelemetryMetrics:
    """Pass a meter from your configured MeterProvider; exporting stays your SDK's job."""

    def __init__(self, meter: Meter) -> None:
        self._leader = meter.create_gauge(
            "goatbeat.leader", description="1 while this scheduler holds the lease."
        )
        self._acquisitions = meter.create_counter(
            "goatbeat.leadership.acquired", description="Times this scheduler became leader."
        )
        self._occurrences = meter.create_counter(
            "goatbeat.occurrences", description="Occurrences by resulting status."
        )
        self._latency = meter.create_histogram(
            "goatbeat.dispatch.latency",
            unit="s",
            description="Delay between the scheduled time and the dispatch.",
        )
        self._tick = meter.create_histogram(
            "goatbeat.tick.duration", unit="s", description="Duration of one scheduler tick."
        )

    def leadership(self, *, is_leader: bool) -> None:
        self._leader.set(1 if is_leader else 0)

    def failover(self) -> None:
        self._acquisitions.add(1)

    def occurrences(self, status: ExecutionStatus, count: int = 1) -> None:
        self._occurrences.add(count, {"status": status.value})

    def dispatch_latency(self, seconds: float) -> None:
        self._latency.record(seconds)

    def tick_duration(self, seconds: float) -> None:
        self._tick.record(seconds)
