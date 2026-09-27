import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import cli_app


@pytest.fixture
def sqlite_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite:///{tmp_path / 'goatbeat.sqlite3'}"
    monkeypatch.setenv("GOATBEAT_DATABASE_URL", url)
    monkeypatch.setenv("GOATBEAT_SCHEDULER_ID", "cli-tests")
    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    cli_app.SUBMITTED.clear()
    return url
