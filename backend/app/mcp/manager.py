import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from app.mcp.contracts import McpConfig, McpServerConfig
from app.mcp.transport import McpConnection, McpConnector, RemoteTool, RemoteToolResult

logger = logging.getLogger(__name__)


class McpError(RuntimeError):
    pass


class McpToolUnavailableError(McpError):
    pass


@dataclass(slots=True)
class _ServerState:
    config: McpServerConfig
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    connection: McpConnection | None = None
    tools: dict[str, RemoteTool] | None = None


class McpManager:
    def __init__(self, config: McpConfig, connector: McpConnector) -> None:
        self._connector = connector
        self._servers = {
            server.id: _ServerState(server) for server in config.servers if server.enabled
        }

    async def discover(self, server_id: str) -> tuple[RemoteTool, ...]:
        state = self._state(server_id)
        async with state.lock:
            await self._ensure_connected(state)
            if state.tools is None:
                assert state.connection is not None
                discovered = await state.connection.list_tools()
                state.tools = {
                    tool.name: tool
                    for tool in discovered
                    if tool.name in state.config.tools
                }
            return tuple(state.tools[name] for name in sorted(state.tools))

    async def call(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> RemoteToolResult:
        state = self._state(server_id)
        policy = state.config.tools.get(tool_name)
        if policy is None:
            raise McpToolUnavailableError(f"MCP tool is not allowlisted: {server_id}.{tool_name}")
        async with state.lock:
            await self._ensure_connected(state)
            if state.tools is None:
                assert state.connection is not None
                discovered = await state.connection.list_tools()
                state.tools = {tool.name: tool for tool in discovered}
            if tool_name not in state.tools:
                raise McpToolUnavailableError(
                    f"MCP tool was not discovered: {server_id}.{tool_name}"
                )
            assert state.connection is not None
            timeout = policy.timeout_seconds or 60.0
            async with asyncio.timeout(timeout):
                return await state.connection.call_tool(tool_name, arguments)

    def statuses(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "id": server_id,
                "transport": state.config.transport.value,
                "enabled": state.config.enabled,
                "status": "healthy" if state.connection is not None else "disconnected",
            }
            for server_id, state in sorted(self._servers.items())
        )

    async def close(self, *, timeout_seconds: float = 0.5) -> None:
        connections = [
            state.connection for state in self._servers.values() if state.connection is not None
        ]
        for connection in connections:
            try:
                async with asyncio.timeout(timeout_seconds):
                    await connection.close()
            except asyncio.CancelledError as error:
                # Some stdio transports surface an internal AnyIO cancel-scope
                # cancellation while closing child processes on Windows. Shutdown is
                # best-effort and must continue closing the remaining connections.
                logger.warning("MCP connection close was cancelled", exc_info=error)
            except Exception as error:
                logger.warning("MCP connection close failed", exc_info=error)
        for state in self._servers.values():
            state.connection = None
            state.tools = None

    async def _ensure_connected(self, state: _ServerState) -> None:
        if state.connection is not None:
            return
        try:
            async with asyncio.timeout(state.config.connect_timeout_seconds):
                state.connection = await self._connector.connect(state.config.id)
        except TimeoutError as error:
            raise McpError(f"MCP connection timed out: {state.config.id}") from error

    def _state(self, server_id: str) -> _ServerState:
        try:
            return self._servers[server_id]
        except KeyError as error:
            raise McpError(f"unknown or disabled MCP server: {server_id}") from error
