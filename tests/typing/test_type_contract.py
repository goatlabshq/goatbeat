"""Static typing is part of the API contract: invalid usages must be rejected by Pyright."""

import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Final, TypedDict

import pytest

HERE: Final = Path(__file__).parent
FIXTURES: Final = HERE / "fixtures"
MARKER: Final = "# expect-error"


class _Position(TypedDict):
    line: int


class _Range(TypedDict):
    start: _Position


class _Diagnostic(TypedDict):
    file: str
    severity: str
    message: str
    range: _Range


class _Report(TypedDict):
    generalDiagnostics: list[_Diagnostic]


@pytest.fixture(scope="module")
def errors_by_file() -> dict[str, set[int]]:
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pyright", "--outputjson", "-p", str(HERE / "pyrightconfig.json")],
        capture_output=True,
        text=True,
        check=False,
    )
    report: _Report = json.loads(completed.stdout)
    errors: defaultdict[str, set[int]] = defaultdict(set)
    for diagnostic in report["generalDiagnostics"]:
        if diagnostic["severity"] == "error":
            errors[Path(diagnostic["file"]).name].add(diagnostic["range"]["start"]["line"] + 1)
    return dict(errors)


def _expected_lines(path: Path) -> set[int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return {number for number, line in enumerate(lines, start=1) if line.endswith(MARKER)}


@pytest.mark.parametrize("fixture", sorted(FIXTURES.glob("*.py")), ids=lambda path: path.name)
def test_pyright_reports_exactly_the_expected_errors(
    fixture: Path, errors_by_file: dict[str, set[int]]
) -> None:
    assert errors_by_file.get(fixture.name, set()) == _expected_lines(fixture)


def test_fixtures_cover_rejections_and_valid_usage() -> None:
    expectations = {path.name: _expected_lines(path) for path in FIXTURES.glob("*.py")}
    assert expectations["accepted.py"] == set()
    assert sum(len(lines) for lines in expectations.values()) >= 11
