"""Smoke test run against the built wheels in a clean environment."""

import goatbeat.core

assert goatbeat.core.__name__ == "goatbeat.core"
print("goatbeat wheels import correctly")
