"""Tool provider extension points.

Providers discover and invoke tools, while AgentLoop only sees the normalized
schemas and executor.  MCP is consequently an implementation detail here,
not a dependency of the loop.
"""

from typing import Any, Protocol

from app.mcp.contracts import McpConfig
from app.mcp.manager import McpManager
from app.mcp.registry import register_mcp_tools
from app.tools.contracts import ToolContext, ToolSource
from app.tools.model_adapter import ModelToolRuntimeAdapter
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime


class ToolProvider(Protocol):
    async def discover(self) -> tuple[dict[str, Any], ...]: ...

    async def invoke(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class RegistryToolProvider:
    """Exposes an existing ToolRegistry as a loop-ready provider."""

    def __init__(self, registry: ToolRegistry, context: ToolContext | None = None) -> None:
        self._registry = registry
        self._adapter = ModelToolRuntimeAdapter(ToolRuntime(registry), context or ToolContext())

    async def discover(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            self._registry.get(name).anthropic_schema() for name in sorted(self._registry.names())
        )

    async def invoke(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._adapter.execute(name, arguments)

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.invoke(name, arguments)

    async def close(self) -> None:
        return None


class McpToolProvider(RegistryToolProvider):
    """Lazily registers and exposes MCP tools through the normal registry path."""

    def __init__(
        self,
        registry: ToolRegistry,
        manager: McpManager,
        config: McpConfig,
        *,
        context: ToolContext | None = None,
    ) -> None:
        super().__init__(registry, context)
        self._manager = manager
        self._config = config
        self._registered = False

    async def discover(self) -> tuple[dict[str, Any], ...]:
        if not self._registered:
            await register_mcp_tools(self._registry, self._manager, self._config)
            self._registered = True
        return tuple(
            self._registry.get(name).anthropic_schema()
            for name in sorted(self._registry.names())
            if self._registry.get(name).source is ToolSource.MCP
        )

    async def close(self) -> None:
        await self._manager.close()


class MultiplexToolProvider:
    """Compose local, MCP, extension, and subagent providers."""

    def __init__(self, providers: tuple[ToolProvider, ...]) -> None:
        self._providers = providers
        self._owners: dict[str, ToolProvider] = {}

    async def discover(self) -> tuple[dict[str, Any], ...]:
        schemas: list[dict[str, Any]] = []
        for provider in self._providers:
            for schema in await provider.discover():
                name = schema.get("name")
                if isinstance(name, str):
                    if name in self._owners:
                        raise ValueError(f"duplicate tool provider name: {name}")
                    self._owners[name] = provider
                    schemas.append(schema)
        return tuple(schemas)

    async def invoke(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        provider = self._owners.get(name)
        if provider is None:
            return {"error": {"code": "tool_unknown"}}
        return await provider.invoke(name, arguments)

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.invoke(name, arguments)

    async def close(self) -> None:
        for provider in self._providers:
            await provider.close()
