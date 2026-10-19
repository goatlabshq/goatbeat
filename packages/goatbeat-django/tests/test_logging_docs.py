import ast
import io
import json
import logging
import logging.config
import re
from pathlib import Path
from typing import Final, cast

from goatbeat.core.observability import Event, log_event

DOCUMENT: Final = Path(__file__).parents[3] / "docs" / "django.md"


def _documented_logging() -> dict[str, object]:
    block = re.search(r"```python\n(LOGGING = \{.*?\n\})\n```", DOCUMENT.read_text(), re.DOTALL)
    assert block is not None
    return cast("dict[str, object]", ast.literal_eval(block.group(1).removeprefix("LOGGING = ")))


def test_the_documented_logging_keeps_structured_fields() -> None:
    logging.config.dictConfig(_documented_logging())
    logger = logging.getLogger("goatbeat")
    stream = io.StringIO()
    handler = logger.handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    handler.setStream(stream)  # pyright: ignore[reportUnknownMemberType]
    try:
        log_event(logger, Event.OCCURRENCE_DISPATCHED, schedule="nightly", idempotency_key="k")
    finally:
        logger.handlers.clear()
        logger.propagate = True
    record = json.loads(stream.getvalue())
    assert record["event"] == "occurrence.dispatched"
    assert (record["schedule"], record["idempotency_key"]) == ("nightly", "k")
