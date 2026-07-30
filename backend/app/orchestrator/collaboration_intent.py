import re
from dataclasses import dataclass

from app.contracts.collaboration import CollaborationMode

_INTENT_PATTERN = re.compile(r"(?<!\w)#(ideate|execute)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class CollaborationIntent:
    message: str
    mode: CollaborationMode
    explicit: bool


def resolve_collaboration_intent(message: str, target_agent_count: int) -> CollaborationIntent:
    explicit_mode: CollaborationMode | None = None
    for match in _INTENT_PATTERN.finditer(message):
        tag = match.group(1).casefold()
        explicit_mode = (
            CollaborationMode.PARALLEL if tag == "ideate" else CollaborationMode.SERIAL
        )
    cleaned = _INTENT_PATTERN.sub("", message)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    if explicit_mode is CollaborationMode.SERIAL:
        mode = CollaborationMode.SERIAL
    elif target_agent_count >= 2:
        mode = CollaborationMode.PARALLEL
    else:
        mode = CollaborationMode.SERIAL
    return CollaborationIntent(
        message=cleaned or message,
        mode=mode,
        explicit=explicit_mode is not None,
    )
