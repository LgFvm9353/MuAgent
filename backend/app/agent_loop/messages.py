from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class AgentMessage:
    role: Role
    content: Any
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] | None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    name: str
    content: Any
    is_error: bool = False
