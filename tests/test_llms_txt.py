import re
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).parent.parent
CONFIG: Final = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")


def _section(name: str) -> str:
    match = re.search(rf"^{name}:\n((?:[ \n].*\n)*)", CONFIG, re.MULTILINE)
    assert match is not None, name
    return match.group(1)


def test_llms_txt_lists_every_page_of_the_navigation() -> None:
    plugins = _section("plugins")
    assert "llmstxt:" in plugins
    assert "full_output: llms-full.txt" in plugins
    navigation = set(re.findall(r":\s*([\w-]+\.md)$", _section("nav"), re.MULTILINE))
    listed = set(re.findall(r"^\s+- ([\w-]+\.md)$", plugins, re.MULTILINE))
    assert navigation
    assert listed == navigation


def test_every_documentation_page_is_in_the_navigation() -> None:
    pages = {path.name for path in (ROOT / "docs").glob("*.md")}
    navigation = set(re.findall(r":\s*([\w-]+\.md)$", _section("nav"), re.MULTILINE))
    assert pages == navigation
