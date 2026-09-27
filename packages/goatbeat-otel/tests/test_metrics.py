from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from goatbeat.core.execution import ExecutionStatus
from goatbeat.otel import OpenTelemetryMetrics


def collected(reader: InMemoryMetricReader) -> dict[str, list[tuple[dict[str, object], object]]]:
    data = reader.get_metrics_data()
    assert data is not None
    found: dict[str, list[tuple[dict[str, object], object]]] = {}
    for resource in data.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                for point in metric.data.data_points:
                    value = getattr(point, "value", None)
                    if value is None:
                        value = getattr(point, "count", None)
                    found.setdefault(metric.name, []).append((dict(point.attributes or {}), value))
    return found


def test_every_call_is_recorded_with_its_attributes() -> None:
    reader = InMemoryMetricReader()
    meter = MeterProvider(metric_readers=[reader]).get_meter("goatbeat-tests")
    metrics = OpenTelemetryMetrics(meter)
    metrics.leadership(is_leader=True)
    metrics.failover()
    metrics.occurrences(ExecutionStatus.DISPATCHED, 2)
    metrics.dispatch_latency(0.25)
    metrics.tick_duration(0.01)
    found = collected(reader)
    assert found["goatbeat.leader"] == [({}, 1)]
    assert found["goatbeat.leadership.acquired"] == [({}, 1)]
    assert found["goatbeat.occurrences"] == [({"status": "dispatched"}, 2)]
    assert found["goatbeat.dispatch.latency"] == [({}, 1)]
    assert found["goatbeat.tick.duration"] == [({}, 1)]
