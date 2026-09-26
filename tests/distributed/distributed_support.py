"""Types shared by the distributed tests (conftest modules cannot be imported by name)."""

import subprocess
from collections.abc import Callable

type SpawnWorker = Callable[[str], subprocess.Popen[bytes]]
