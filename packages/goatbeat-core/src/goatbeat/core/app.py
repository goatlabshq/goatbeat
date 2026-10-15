from dataclasses import dataclass, field

from goatbeat.core.observability import MetricsSink, NoopMetrics
from goatbeat.core.protocols import TaskSubmitter
from goatbeat.core.registry import SupportsDefinitions


@dataclass(frozen=True, slots=True)
class GoatbeatApp:
    registry: SupportsDefinitions
    submitter: TaskSubmitter
    metrics: MetricsSink = field(default_factory=NoopMetrics)
