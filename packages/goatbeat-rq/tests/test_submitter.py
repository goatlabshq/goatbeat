import hashlib
from datetime import UTC, datetime
from typing import cast

import fakeredis
import pytest
from redis import Redis
from rq import Queue

from goatbeat.core.errors import SubmissionError
from goatbeat.core.ids import IdempotencyKey, ScheduleId
from goatbeat.core.schedule import Routing
from goatbeat.core.submission import TaskSubmission
from goatbeat.core.tasks import TaskCall
from goatbeat.core.time import Instant
from goatbeat.rq import RQSubmitter, job_id_for

KEY = IdempotencyKey("s:2026-01-01T00:00:00+00:00")


def submission(routing: Routing | None = None) -> TaskSubmission:
    return TaskSubmission(
        schedule_id=ScheduleId("s"),
        schedule_name="job",
        scheduled_at=Instant.of(datetime(2026, 1, 1, tzinfo=UTC)),
        idempotency_key=KEY,
        task=TaskCall("app.tasks.send_email", (42,), {"subject": "hi"}),
        routing=routing or Routing(),
    )


@pytest.fixture
def redis() -> Redis:
    return fakeredis.FakeRedis()


def test_the_job_id_is_derived_from_the_idempotency_key(redis: Redis) -> None:
    receipt = RQSubmitter(redis).submit(submission(Routing(queue="low")))
    expected = "goatbeat-" + hashlib.sha256(KEY.value.encode()).hexdigest()
    assert job_id_for(KEY) == expected
    assert receipt.result_id == expected
    queue = Queue("low", connection=redis)
    [job] = queue.get_jobs()
    assert job.id == expected
    assert job.func_name == "app.tasks.send_email"
    arguments = cast("tuple[object, ...]", job.args)  # pyright: ignore[reportUnknownMemberType]
    assert (arguments, job.kwargs) == ((42,), {"subject": "hi"})


def test_resubmitting_reuses_the_job_id(redis: Redis) -> None:
    submitter = RQSubmitter(redis)
    submitter.submit(submission())
    submitter.submit(submission())
    # RQ does not deduplicate: the id is queued twice and would run twice (at least once).
    assert set(Queue("default", connection=redis).job_ids) == {job_id_for(KEY)}


@pytest.mark.parametrize("routing", [Routing(priority=1), Routing(backend="other")])
def test_unsupported_routing_is_rejected(redis: Redis, routing: Routing) -> None:
    with pytest.raises(SubmissionError):
        RQSubmitter(redis).submit(submission(routing))


def test_a_redis_failure_is_a_submission_error() -> None:
    unreachable = Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.2)
    with pytest.raises(SubmissionError):
        RQSubmitter(unreachable).submit(submission())
