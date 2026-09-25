"""Goatbeat: a type-safe, distributed periodic task scheduler."""

from pkgutil import extend_path

# Editable installs give each workspace package its own sys.path entry; extending __path__
# lets goatbeat.core, goatbeat.postgres, ... resolve as portions of this regular package.
__path__ = extend_path(__path__, __name__)

from goatbeat.core.config import GoatbeatConfig
from goatbeat.core.errors import (
    ConfigurationError,
    GoatbeatError,
    InvalidCronExpressionError,
    InvalidIntervalError,
    LeaseLostError,
    StoreUnavailableError,
    SubmissionError,
    TaskNotFoundError,
)
from goatbeat.core.execution import ExecutionStatus
from goatbeat.core.misfire import MisfirePolicy
from goatbeat.core.registry import Registry
from goatbeat.core.scheduler import Scheduler
from goatbeat.core.stores.memory import MemoryStore
from goatbeat.core.stores.sqlite import SQLiteStore
from goatbeat.core.submitters import CallableSubmitter
from goatbeat.core.tasks import TaskCall, call

__all__ = [
    "CallableSubmitter",
    "ConfigurationError",
    "ExecutionStatus",
    "GoatbeatConfig",
    "GoatbeatError",
    "InvalidCronExpressionError",
    "InvalidIntervalError",
    "LeaseLostError",
    "MemoryStore",
    "MisfirePolicy",
    "Registry",
    "SQLiteStore",
    "Scheduler",
    "StoreUnavailableError",
    "SubmissionError",
    "TaskCall",
    "TaskNotFoundError",
    "call",
]
