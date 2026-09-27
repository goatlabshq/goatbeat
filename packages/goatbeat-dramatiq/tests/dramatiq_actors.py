"""Actors resolved by import path in the tests."""

import dramatiq
from dramatiq.brokers.stub import StubBroker

broker = StubBroker()
broker.emit_after("process_boot")
dramatiq.set_broker(broker)


@dramatiq.actor(queue_name="default")
def send_email(user_id: int, subject: str = "hello") -> None:
    del user_id, subject


NOT_AN_ACTOR = 42
