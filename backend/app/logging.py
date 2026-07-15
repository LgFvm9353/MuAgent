import logging
import sys
from collections.abc import MutableMapping
from typing import Any, cast

import structlog
from structlog.typing import EventDict, Processor

from app.redaction import redact


def _redact_event(
    _: object,
    __: str,
    event_dict: MutableMapping[str, Any],
) -> EventDict:
    return cast(EventDict, redact(dict(event_dict)))


def configure_logging(level: str) -> None:
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        _redact_event,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.JSONRenderer(),
    ]
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def logger() -> structlog.stdlib.BoundLogger:
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger())
