"""goatbeat.core must stay framework-agnostic: importing it loads no framework or driver."""

import json
import pkgutil
import subprocess
import sys
from typing import Final

import goatbeat.core

FORBIDDEN: Final = frozenset(
    {"django", "celery", "dramatiq", "rq", "psycopg", "prometheus_client", "opentelemetry"}
)


def _core_modules() -> list[str]:
    return [
        info.name
        for info in pkgutil.walk_packages(goatbeat.core.__path__, prefix="goatbeat.core.")
        if ".testing" not in info.name
    ]


def test_core_imports_no_framework_or_driver() -> None:
    script = (
        "import importlib, json, sys\n"
        f"for name in {_core_modules()!r} + ['goatbeat.core']:\n"
        "    importlib.import_module(name)\n"
        "print(json.dumps(sorted({m.split('.')[0] for m in sys.modules})))\n"
    )
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    loaded: set[str] = set(json.loads(completed.stdout))
    assert loaded.isdisjoint(FORBIDDEN)
