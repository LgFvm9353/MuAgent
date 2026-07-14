import logging
import sys
from typing import Any

import structlog

from app.redaction import redact


def _redact_event(
    _: object,
    __: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    return redact(event_dict)


def configure_logging(level: str) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _redact_event,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def logger() -> structlog.stdlib.BoundLogger:
    return structlog.get_logger()
