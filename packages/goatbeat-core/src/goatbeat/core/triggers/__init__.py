"""Triggers compute the next occurrence strictly after a given instant."""

from goatbeat.core.triggers.cron import CronTrigger
from goatbeat.core.triggers.interval import IntervalTrigger

type Trigger = IntervalTrigger | CronTrigger

__all__ = ["CronTrigger", "IntervalTrigger", "Trigger"]
