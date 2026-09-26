"""LISTEN/NOTIFY wake-ups, so schedulers see schedule changes before their next poll."""

from datetime import timedelta
from typing import Protocol


class Notifier(Protocol):
    def wait(self, timeout: timedelta) -> bool:
        """Block until a change notification or the timeout; True when notified."""
        ...
