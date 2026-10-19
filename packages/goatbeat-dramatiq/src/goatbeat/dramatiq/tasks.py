from __future__ import annotations

from typing import TYPE_CHECKING

from goatbeat.core.json import ensure_json
from goatbeat.core.tasks import TaskCall

if TYPE_CHECKING:
    from dramatiq import Actor


def call[**P, R](actor: Actor[P, R], /, *args: P.args, **kwargs: P.kwargs) -> TaskCall:
    return TaskCall(
        path=f"{actor.fn.__module__}.{actor.fn.__qualname__}",
        args=tuple(ensure_json(value) for value in args),
        kwargs={name: ensure_json(value) for name, value in kwargs.items()},
    )
