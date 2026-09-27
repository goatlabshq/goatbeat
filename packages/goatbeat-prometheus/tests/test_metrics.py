from prometheus_client import CollectorRegistry

from goatbeat.core.execution import ExecutionStatus
from goatbeat.prometheus import PrometheusMetrics


def test_every_call_is_recorded_with_its_labels() -> None:
    registry = CollectorRegistry()
    metrics = PrometheusMetrics(registry)
    metrics.leadership(is_leader=True)
    metrics.failover()
    metrics.occurrences(ExecutionStatus.DISPATCHED, 2)
    metrics.occurrences(ExecutionStatus.SKIPPED)
    metrics.dispatch_latency(0.25)
    metrics.tick_duration(0.01)
    sample = registry.get_sample_value
    assert sample("goatbeat_leader") == 1
    assert sample("goatbeat_leadership_acquired_total") == 1
    assert sample("goatbeat_occurrences_total", {"status": "dispatched"}) == 2
    assert sample("goatbeat_occurrences_total", {"status": "skipped"}) == 1
    assert sample("goatbeat_dispatch_latency_seconds_count") == 1
    assert sample("goatbeat_dispatch_latency_seconds_sum") == 0.25
    assert sample("goatbeat_tick_duration_seconds_count") == 1
    metrics.leadership(is_leader=False)
    assert sample("goatbeat_leader") == 0


def test_two_sinks_can_share_nothing() -> None:
    PrometheusMetrics(CollectorRegistry())
    PrometheusMetrics(CollectorRegistry())
