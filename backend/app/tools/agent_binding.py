from dataclasses import dataclass
from typing import Any

from app.contracts.task import RiskLevel
from app.harness.registry import AgentDefinition
from app.tools.contracts import ToolContext
from app.tools.model_adapter import ModelToolRuntimeAdapter
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime


@dataclass(frozen=True, slots=True)
class AgentToolBinding:
    schemas: tuple[dict[str, Any], ...]
    executor: ModelToolRuntimeAdapter


def bind_agent_tools(
    registry: ToolRegistry | None,
    definition: AgentDefinition,
    context: ToolContext,
    *,
    allowed_tools: frozenset[str] | None = None,
    maximum_risk: RiskLevel = RiskLevel.LOW,
) -> AgentToolBinding | None:
    if registry is None:
        return None
    definitions = registry.model_tools(
        allowed_tools or definition.allowed_tools,
        maximum_risk=maximum_risk,
    )
    if not definitions:
        return None
    allowed = frozenset(definition.name for definition in definitions)
    runtime = ToolRuntime(registry)
    executor = ModelToolRuntimeAdapter(
        runtime,
        context.model_copy(update={"allowed_tools": allowed}),
    )
    return AgentToolBinding(
        schemas=tuple(definition.anthropic_schema() for definition in definitions),
        executor=executor,
    )
