import re
from collections.abc import Mapping
from typing import Any

_SECRET_KEYS = re.compile(r"(api[_-]?key|authorization|token|password|secret)", re.IGNORECASE)
_BEARER = re.compile(r"(?i)bearer\s+[a-z0-9._-]+")


def sanitize_text(value: str) -> str:
    return _BEARER.sub("Bearer [REDACTED]", value).replace("\r", "\\r").replace("\n", "\\n")


def redact(value: Any, *, key: str | None = None) -> Any:
    if key is not None and _SECRET_KEYS.search(key):
        return "[REDACTED]"
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, Mapping):
        return {
            str(item_key): redact(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value
