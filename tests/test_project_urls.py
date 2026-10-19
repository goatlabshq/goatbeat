import re
import tomllib
from pathlib import Path
from typing import Final

import pytest

ROOT: Final = Path(__file__).parent.parent
REPOSITORY: Final = "https://github.com/goatlabshq/goatbeat"
DOCUMENTATION: Final = "https://goatlabshq.github.io/goatbeat/"
PACKAGES: Final = sorted((ROOT / "packages").glob("*/pyproject.toml"))


@pytest.mark.parametrize("pyproject", PACKAGES, ids=lambda path: path.parent.name)
def test_every_package_links_the_repository_and_the_documentation(pyproject: Path) -> None:
    urls = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["urls"]
    assert urls == {
        "Homepage": REPOSITORY,
        "Documentation": DOCUMENTATION,
        "Issues": f"{REPOSITORY}/issues",
    }


def test_the_documentation_site_names_its_url_and_repository() -> None:
    config = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    assert f"repo_url: {REPOSITORY}\n" in config
    assert f"site_url: {DOCUMENTATION}\n" in config


def test_no_document_links_another_github_repository() -> None:
    documents = [ROOT / "README.md", *ROOT.glob("packages/*/README.md"), *ROOT.glob("docs/*.md")]
    for document in documents:
        for url in re.findall(r"https://github\.com/[\w.-]+/[\w.-]+", document.read_text()):
            assert url == REPOSITORY, f"{document.name}: {url}"
