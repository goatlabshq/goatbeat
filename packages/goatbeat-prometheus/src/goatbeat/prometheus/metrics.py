"""A MetricsSink exporting to a prometheus_client registry."""

from typing import Final

from prometheus_client import REGISTRY, CollectorRegistry, Counter, Gauge, Histogram

from goatbeat.core.execution import ExecutionStatus

# Dispatch latency spans sub-second dispatches to catch-up after hours of downtime.
LATENCY_BUCKETS: Final = (0.01, 0.05, 0.1, 0.5, 1, 5, 15, 60, 300, 1800, 3600)


class PrometheusMetrics:
    def __init__(self, registry: CollectorRegistry = REGISTRY) -> None:
        self._leader = Gauge(
            "goatbeat_leader", "1 while this scheduler holds the lease.", registry=registry
        )
        self._acquisitions = Counter(
            "goatbeat_leadership_acquired",
            "Times this scheduler became leader.",
            registry=registry,
        )
        self._occurrences = Counter(
            "goatbeat_occurrences",
            "Occurrences by resulting status.",
            ["status"],
            registry=registry,
        )
        self._latency = Histogram(
            "goatbeat_dispatch_latency_seconds",
            "Delay between the scheduled time and the dispatch.",
            buckets=LATENCY_BUCKETS,
            registry=registry,
        )
        self._tick = Histogram(
            "goatbeat_tick_duration_seconds", "Duration of one scheduler tick.", registry=registry
        )

    def leadership(self, *, is_leader: bool) -> None:
        self._leader.set(1 if is_leader else 0)

    def failover(self) -> None:
        self._acquisitions.inc()

    def occurrences(self, status: ExecutionStatus, count: int = 1) -> None:
        self._occurrences.labels(status=status.value).inc(count)

    def dispatch_latency(self, seconds: float) -> None:
        self._latency.observe(seconds)

    def tick_duration(self, seconds: float) -> None:
        self._tick.observe(seconds)
