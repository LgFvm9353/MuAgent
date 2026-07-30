from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class RemoteTool:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RemoteToolResult:
    content: tuple[dict[str, Any], ...]
    is_error: bool = False


class McpConnection(Protocol):
    async def list_tools(self) -> tuple[RemoteTool, ...]: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> RemoteToolResult: ...

    async def close(self) -> None: ...


class McpConnector(Protocol):
    async def connect(self, server_id: str) -> McpConnection: ...
