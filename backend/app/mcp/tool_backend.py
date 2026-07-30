from typing import Any

from pydantic import BaseModel, ConfigDict

from app.mcp.manager import McpManager


class McpToolInput(BaseModel):
    model_config = ConfigDict(extra="allow")


class McpToolOutput(BaseModel):
    content: tuple[dict[str, Any], ...]
    is_error: bool = False


class McpToolBackend:
    def __init__(self, manager: McpManager, server_id: str, tool_name: str) -> None:
        self._manager = manager
        self._server_id = server_id
        self._tool_name = tool_name

    async def __call__(self, request: McpToolInput) -> McpToolOutput:
        result = await self._manager.call(
            self._server_id,
            self._tool_name,
            request.model_dump(mode="json"),
        )
        return McpToolOutput(content=result.content, is_error=result.is_error)
