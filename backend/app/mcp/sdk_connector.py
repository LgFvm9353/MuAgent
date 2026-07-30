from contextlib import AsyncExitStack
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from app.mcp.config import resolved_headers
from app.mcp.contracts import McpServerConfig, McpTransport
from app.mcp.transport import McpConnection, RemoteTool, RemoteToolResult


class SdkMcpConnection:
    def __init__(self, stack: AsyncExitStack, session: ClientSession) -> None:
        self._stack = stack
        self._session = session

    async def list_tools(self) -> tuple[RemoteTool, ...]:
        response = await self._session.list_tools()
        return tuple(
            RemoteTool(
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.inputSchema,
            )
            for tool in response.tools
        )

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> RemoteToolResult:
        response = await self._session.call_tool(name, arguments)
        content = tuple(item.model_dump(mode="json") for item in response.content)
        return RemoteToolResult(content=content, is_error=bool(response.isError))

    async def close(self) -> None:
        await self._stack.aclose()


class SdkMcpConnector:
    def __init__(self, servers: tuple[McpServerConfig, ...]) -> None:
        self._servers = {server.id: server for server in servers if server.enabled}

    async def connect(self, server_id: str) -> McpConnection:
        try:
            server = self._servers[server_id]
        except KeyError as error:
            raise LookupError(server_id) from error
        stack = AsyncExitStack()
        try:
            if server.transport is McpTransport.STDIO:
                parameters = StdioServerParameters(
                    command=server.command or "",
                    args=list(server.args),
                    cwd=server.cwd,
                    env=server.env or None,
                )
                read, write = await stack.enter_async_context(stdio_client(parameters))
            else:
                client = httpx.AsyncClient(
                    headers=resolved_headers(server),
                    follow_redirects=False,
                )
                await stack.enter_async_context(client)
                read, write, _ = await stack.enter_async_context(
                    streamable_http_client(str(server.url), http_client=client)
                )
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            return SdkMcpConnection(stack, session)
        except Exception:
            await stack.aclose()
            raise
