import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from cli_app import SUBMITTED

from goatbeat.cli.main import main
from goatbeat.postgres.testing import database_url_from_env, isolated_schema

APP = ["--app", "cli_app:app"]
TESTS = Path(__file__).parent


def run(capsys: pytest.CaptureFixture[str], *arguments: str) -> tuple[int, str, str]:
    code = main(list(arguments))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_a_missing_database_url_is_a_configuration_error(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GOATBEAT_DATABASE_URL", raising=False)
    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    code, _, err = run(capsys, *APP, "status")
    assert code == 3
    assert "GOATBEAT_DATABASE_URL" in err


@pytest.mark.usefixtures("sqlite_url")
@pytest.mark.parametrize("app", [None, "cli_app:missing", "cli_app:not_an_app", "nowhere:app"])
def test_an_unusable_app_is_a_configuration_error(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, app: str | None
) -> None:
    monkeypatch.delenv("GOATBEAT_APP", raising=False)
    arguments = ["status"] if app is None else ["--app", app, "status"]
    code, _, err = run(capsys, *arguments)
    assert code == 3
    assert err


@pytest.mark.usefixtures("sqlite_url")
def test_the_app_can_come_from_the_environment(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOATBEAT_APP", "cli_app:app")
    code, out, _ = run(capsys, "schedule", "list", "--json")
    assert code == 0
    assert [item["name"] for item in json.loads(out)] == ["ping"]


@pytest.mark.usefixtures("sqlite_url")
def test_a_requested_run_is_dispatched_by_the_next_tick(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, *APP, "schedule", "run", "ping")
    assert code == 0
    key = out.split()[0]
    assert key.startswith("manual:")
    assert run(capsys, *APP, "scheduler", "--once")[0] == 0
    assert [key] == SUBMITTED


@pytest.mark.usefixtures("sqlite_url")
def test_running_an_unknown_schedule_fails(capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run(capsys, *APP, "schedule", "run", "nope")
    assert code == 1
    assert "nope" in err


@pytest.mark.usefixtures("sqlite_url")
def test_status_reports_the_leader_and_schedules(capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, *APP, "scheduler", "--once")
    code, out, _ = run(capsys, *APP, "status", "--json")
    status = json.loads(out)
    assert code == 0
    assert status["leader"]["holder"] == "cli-tests"
    assert status["leader"]["token"] == 1
    assert status["schedules"] == {"total": 1, "enabled": 1}
    assert status["next_wakeup"].endswith("+00:00")


@pytest.mark.usefixtures("sqlite_url")
def test_doctor_passes_on_a_healthy_setup(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, *APP, "doctor", "--json")
    checks = {check["name"]: check for check in json.loads(out)}
    assert code == 0
    assert checks["store"]["ok"]
    assert checks["tasks"]["ok"]


@pytest.mark.usefixtures("sqlite_url")
def test_doctor_fails_on_a_task_that_does_not_import(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "--app", "cli_app:broken_app", "doctor")
    assert code == 1
    assert "cli_app.missing" in out


@pytest.mark.usefixtures("sqlite_url")
def test_an_unknown_database_scheme_is_a_configuration_error(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOATBEAT_DATABASE_URL", "mysql://db/goatbeat")
    assert run(capsys, *APP, "status")[0] == 3


@pytest.mark.usefixtures("sqlite_url")
def test_an_unreachable_database_exits_with_store_unavailable(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "GOATBEAT_DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none?connect_timeout=1"
    )
    assert run(capsys, *APP, "status")[0] == 4


@pytest.mark.usefixtures("sqlite_url")
def test_a_metrics_port_serves_prometheus_metrics(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ports: list[int] = []
    monkeypatch.setattr("goatbeat.cli.environment.start_http_server", ports.append)
    assert run(capsys, *APP, "scheduler", "--once", "--metrics-port", "9464")[0] == 0
    assert ports == [9464]


def test_postgresql_is_migrated_and_checked(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    url = database_url_from_env()
    if url is None:
        pytest.skip("GOATBEAT_TEST_DATABASE_URL is not set")
    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    with isolated_schema(url) as scoped:
        monkeypatch.setenv("GOATBEAT_DATABASE_URL", scoped)
        before, out, _ = run(capsys, *APP, "doctor")
        assert before == 1
        assert "schema" in out
        assert run(capsys, *APP, "migrate")[0] == 0
        code, out, _ = run(capsys, *APP, "doctor", "--json")
        checks = {check["name"]: check["ok"] for check in json.loads(out)}
        assert code == 0
        assert checks == {"store": True, "tasks": True, "schema": True, "clock": True}


def test_sigterm_stops_the_scheduler_and_releases_the_lease(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'goatbeat.sqlite3'}"
    environment = os.environ | {
        "GOATBEAT_DATABASE_URL": url,
        "GOATBEAT_SCHEDULER_ID": "cli-sigterm",
        "PYTHONPATH": str(TESTS),
    }
    environment.pop("DJANGO_SETTINGS_MODULE", None)
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "goatbeat.cli.main", *APP, "scheduler"], env=environment
    )
    time.sleep(1.5)
    process.send_signal(signal.SIGTERM)
    assert process.wait(timeout=10) == 0
    status = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "goatbeat.cli.main", *APP, "status", "--json"],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(status.stdout)["leader"]["held"] is False


def test_a_fresh_postgresql_database_asks_for_a_migration(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    url = database_url_from_env()
    if url is None:
        pytest.skip("GOATBEAT_TEST_DATABASE_URL is not set")
    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)
    with isolated_schema(url) as scoped:
        monkeypatch.setenv("GOATBEAT_DATABASE_URL", scoped)
        for command in (["status"], ["schedule", "list"], ["scheduler", "--once"]):
            code, _, err = run(capsys, *APP, *command)
            assert code == 3, command
            assert "goatbeat migrate" in err


@pytest.mark.usefixtures("sqlite_url")
def test_doctor_reports_a_task_module_that_fails_to_import(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, _ = run(capsys, "--app", "cli_app:app_with_broken_module", "doctor")
    assert code == 1
    assert "broken_tasks.run" in out
    assert "nonexistent_dependency_for_goatbeat_tests" in out


@pytest.mark.usefixtures("sqlite_url")
@pytest.mark.parametrize("url", ["sqlite://host/x.db", "sqlite:/abs.db", "sqlite:///"])
def test_malformed_sqlite_urls_are_configuration_errors(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("GOATBEAT_DATABASE_URL", url)
    code, _, err = run(capsys, *APP, "status")
    assert code == 3
    assert "Traceback" not in err


@pytest.mark.usefixtures("sqlite_url")
def test_an_unexpected_error_has_its_own_exit_code(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*args: object, **kwargs: object) -> int:
        del args, kwargs
        raise RuntimeError("boom")

    monkeypatch.setattr("goatbeat.cli.commands.status", explode)
    code, _, err = run(capsys, *APP, "status")
    assert code == 5
    assert "boom" in err


@pytest.mark.usefixtures("sqlite_url")
def test_app_prometheus_metrics_are_reused_by_the_metrics_port(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ports: list[int] = []
    monkeypatch.setattr("goatbeat.cli.environment.start_http_server", ports.append)
    arguments = ("--app", "cli_app:app_with_prometheus", "scheduler", "--once")
    assert run(capsys, *arguments, "--metrics-port", "9464")[0] == 0
    assert run(capsys, *arguments, "--metrics-port", "9465")[0] == 0
    assert ports == [9464, 9465]


@pytest.mark.usefixtures("sqlite_url")
def test_a_single_tick_releases_the_lease(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, *APP, "scheduler", "--once")[0] == 0
    status = json.loads(run(capsys, *APP, "status", "--json")[1])
    assert status["leader"]["held"] is False


@pytest.mark.usefixtures("sqlite_url")
def test_scheduler_events_are_logged_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run(capsys, *APP, "--log-format", "json", "scheduler", "--once")
    assert code == 0
    events = [json.loads(line)["event"] for line in err.splitlines() if line.startswith("{")]
    assert "lease.acquired" in events


def test_a_missing_django_settings_module_is_reported_as_such(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "nosuch.settings")
    monkeypatch.delenv("GOATBEAT_APP", raising=False)
    code, _, err = run(capsys, "status")
    assert code == 3
    assert "nosuch.settings" in err
    assert "pip install" not in err
