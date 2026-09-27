"""A task module whose own import fails, the way a missing dependency breaks production."""

import nonexistent_dependency_for_goatbeat_tests  # noqa: F401  # pyright: ignore[reportMissingImports, reportUnusedImport]


def run() -> None: ...
