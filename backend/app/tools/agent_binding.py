from dataclasses import dataclass
from typing import Any

from app.harness.registry import AgentDefinition
from app.tools.contracts import ToolContext
from app.tools.model_adapter import ModelToolRuntimeAdapter
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime


@dataclass(frozen=True, slots=True)
class AgentToolBinding:
    schemas: tuple[dict[str, Any], ...]
    executor: "BudgetedModelToolAdapter"


class BudgetedModelToolAdapter:
    def __init__(self, delegate: ModelToolRuntimeAdapter, max_calls: int) -> None:
        self._delegate = delegate
        self._max_calls = max_calls
        self._calls = 0

    @property
    def calls(self) -> int:
        return self._calls

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._calls >= self._max_calls:
            return {"error": {"code": "tool_budget_exhausted"}}
        self._calls += 1
        return await self._delegate.execute(name, arguments)


def bind_agent_tools(
    registry: ToolRegistry | None,
    definition: AgentDefinition,
    context: ToolContext,
    *,
    max_calls: int,
    allowed_tools: frozenset[str] | None = None,
) -> AgentToolBinding | None:
    if registry is None or max_calls <= 0:
        return None
    definitions = registry.model_tools(allowed_tools or definition.allowed_tools)
    if not definitions:
        return None
    allowed = frozenset(definition.name for definition in definitions)
    runtime = ToolRuntime(registry)
    executor = BudgetedModelToolAdapter(
        ModelToolRuntimeAdapter(
            runtime,
            context.model_copy(update={"allowed_tools": allowed}),
        ),
        max_calls,
    )
    return AgentToolBinding(
        schemas=tuple(definition.anthropic_schema() for definition in definitions),
        executor=executor,
    )
