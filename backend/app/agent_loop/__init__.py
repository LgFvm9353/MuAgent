"""Provider-neutral, model-driven agent loop.

The loop owns conversation state and tool lifecycle.  Model gateways only
implement one model turn; tools (including MCP and subagents) are regular
executors from the loop's perspective.
"""

from .loop import (
    AgentAbortedError,
    AgentLoop,
    AgentLoopConfig,
    AgentLoopError,
    AgentLoopEvent,
    AgentLoopResult,
    ToolExecutor,
)
from .messages import AgentMessage, ToolCall, ToolResult
from .providers import ModelTurn, ModelTurnProvider, TextDeltaSink

__all__ = [
    "AgentAbortedError",
    "AgentLoop",
    "AgentLoopConfig",
    "AgentLoopError",
    "AgentLoopEvent",
    "AgentLoopResult",
    "AgentMessage",
    "ModelTurn",
    "ModelTurnProvider",
    "TextDeltaSink",
    "ToolCall",
    "ToolExecutor",
    "ToolResult",
]
