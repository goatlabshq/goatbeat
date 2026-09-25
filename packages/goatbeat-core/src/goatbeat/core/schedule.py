"""Schedule definitions (what the user declares) and schedules (what a store holds)."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from goatbeat.core.errors import ConfigurationError
from goatbeat.core.ids import ScheduleId
from goatbeat.core.misfire import MisfireRules
from goatbeat.core.tasks import TaskCall
from goatbeat.core.time import Instant
from goatbeat.core.triggers import Trigger

MAX_NAME_LENGTH: Final = 200


class ScheduleSource(StrEnum):
    CODE = "code"
    STORE = "store"


@dataclass(frozen=True, slots=True)
class Routing:
    """Backend-interpreted submission options."""

    queue: str | None = None
    priority: int | None = None
    backend: str | None = None


@dataclass(frozen=True, slots=True)
class ScheduleDefinition:
    name: str
    task: TaskCall
    trigger: Trigger
    misfire: MisfireRules = field(default_factory=MisfireRules)
    routing: Routing = field(default_factory=Routing)
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip() or len(self.name) > MAX_NAME_LENGTH:
            raise ConfigurationError(
                f"schedule name must be 1 to {MAX_NAME_LENGTH} visible characters, "
                f"got {self.name!r}"
            )


@dataclass(frozen=True, slots=True)
class Schedule:
    id: ScheduleId
    definition: ScheduleDefinition
    source: ScheduleSource
    next_run_at: Instant

    @property
    def name(self) -> str:
        return self.definition.name
