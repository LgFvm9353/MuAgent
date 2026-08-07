from dataclasses import dataclass
from typing import Any, Protocol

from .messages import ToolCall, ToolResult


@dataclass(frozen=True, slots=True)
class ModelTurn:
    """The provider-specific response normalized for AgentLoop."""

    content: Any
    stop_reason: str
    tool_calls: tuple[ToolCall, ...]
    usage: Any
    assistant_message: dict[str, Any]


class ModelTurnProvider(Protocol):
    async def turn(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: tuple[dict[str, Any], ...],
        max_tokens: int,
        effort: str,
    ) -> ModelTurn: ...

    def tool_result_messages(self, results: tuple[ToolResult, ...]) -> list[dict[str, Any]]: ...
