from dataclasses import dataclass

from goatbeat.core.execution import Execution
from goatbeat.core.ids import IdempotencyKey, ScheduleId
from goatbeat.core.schedule import Routing, Schedule
from goatbeat.core.tasks import TaskCall
from goatbeat.core.time import Instant


@dataclass(frozen=True, slots=True)
class TaskSubmission:
    schedule_id: ScheduleId
    schedule_name: str
    scheduled_at: Instant
    idempotency_key: IdempotencyKey
    task: TaskCall
    routing: Routing


@dataclass(frozen=True, slots=True)
class PendingSubmission:
    execution: Execution
    schedule: Schedule

    def to_submission(self) -> TaskSubmission:
        return TaskSubmission(
            schedule_id=self.schedule.id,
            schedule_name=self.schedule.name,
            scheduled_at=self.execution.scheduled_at,
            idempotency_key=self.execution.idempotency_key,
            task=self.schedule.definition.task,
            routing=self.schedule.definition.routing,
        )
