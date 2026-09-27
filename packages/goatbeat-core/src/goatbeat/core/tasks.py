"""Typed task references: the arguments of a scheduled call are checked against its signature."""

import importlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from goatbeat.core.errors import ConfigurationError, TaskNotFoundError
from goatbeat.core.json import JsonValue, ensure_json

_MISSING = object()


@dataclass(frozen=True, slots=True)
class TaskCall:
    path: str
    args: tuple[JsonValue, ...] = ()
    kwargs: Mapping[str, JsonValue] = field(default_factory=dict[str, JsonValue])

    def __post_init__(self) -> None:
        ensure_json(list(self.args))
        ensure_json(dict(self.kwargs))


def call[**P](task: Callable[P, object], /, *args: P.args, **kwargs: P.kwargs) -> TaskCall:
    return TaskCall(
        path=task_path(task),
        args=tuple(ensure_json(value) for value in args),
        kwargs={name: ensure_json(value) for name, value in kwargs.items()},
    )


def task_path(task: object) -> str:
    """Dotted import path of a task; objects exposing ``module_path`` (Django Tasks) win."""
    module_path: object = getattr(task, "module_path", None)
    if isinstance(module_path, str):
        return module_path
    module: object = getattr(task, "__module__", None)
    qualname: object = getattr(task, "__qualname__", None)
    if not isinstance(module, str) or not isinstance(qualname, str) or "<" in qualname:
        raise ConfigurationError(f"{task!r} is not importable by path; use a module-level function")
    return f"{module}.{qualname}"


def import_object(path: str) -> object:
    """Import ``package.module.attribute.nested`` by trying the longest module prefix first."""
    parts = path.split(".")
    for split in range(len(parts) - 1, 0, -1):
        module_name = ".".join(parts[:split])
        try:
            target: object = importlib.import_module(module_name)
        except ModuleNotFoundError as error:
            if error.name is not None and (
                module_name == error.name or module_name.startswith(f"{error.name}.")
            ):
                continue
            raise
        for attribute in parts[split:]:
            target = getattr(target, attribute, _MISSING)
            if target is _MISSING:
                raise TaskNotFoundError(f"nothing importable at {path!r}")
        return target
    raise TaskNotFoundError(f"nothing importable at {path!r}")


def import_task(path: str) -> Callable[..., object]:
    target = import_object(path)
    if not callable(target):
        raise TaskNotFoundError(f"no callable task at {path!r}")
    return target
