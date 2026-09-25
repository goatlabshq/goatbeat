"""commit-msg hook: a single-line conventional commit subject."""

import re
import sys
from pathlib import Path
from typing import Final

TYPES: Final = "build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test"
SUBJECT: Final = re.compile(rf"^(?:{TYPES})(?:\([a-z0-9-]+\))?!?: \S.*$")
EXEMPT: Final = re.compile(r"^(?:Merge |Revert \"|fixup! |squash! )")


def check(message: str) -> str | None:
    lines = [line for line in message.splitlines() if not line.startswith("#")]
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return "the commit message is empty"
    if EXEMPT.match(lines[0]):
        return None
    if not SUBJECT.match(lines[0]):
        return f"{lines[0]!r} is not a conventional commit subject ({TYPES})"
    if len(lines) > 1:
        return "use a single subject line, without a body"
    return None


def main() -> int:
    error = check(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if error is not None:
        print(f"commit-msg: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
