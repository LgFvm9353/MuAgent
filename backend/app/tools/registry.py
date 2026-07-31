from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.contracts.task import RiskLevel
from app.tools.contracts import ToolSource


@dataclass(frozen=True, slots=True)
class ToolDefinition[InputT: BaseModel, OutputT: BaseModel]:
    name: str
    description: str
    input_model: type[InputT]
    output_model: type[OutputT]
    risk: RiskLevel
    timeout_seconds: float
    idempotent: bool
    max_output_bytes: int
    handler: Callable[[InputT], Awaitable[OutputT]]
    validate_input: Callable[[InputT], None] | None = None
    planning_constraints: dict[str, Any] | None = None
    input_json_schema: dict[str, Any] | None = None
    source: ToolSource = ToolSource.LOCAL
    canonical_id: str | None = None

    @property
    def canonical_tool_id(self) -> str:
        return self.canonical_id or f"{self.source.value}.{self.name}"

    def input_schema(self) -> dict[str, Any]:
        if self.input_json_schema is not None:
            return self.input_json_schema
        schema = self.input_model.model_json_schema()
        schema["additionalProperties"] = False
        properties = schema.get("properties", {})
        schema["required"] = sorted(properties)
        return schema

    def anthropic_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema(),
            "strict": True,
        }

    def planning_schema(self) -> dict[str, Any]:
        schema = {
            **self.anthropic_schema(),
            "risk": self.risk.value,
            "idempotent": self.idempotent,
        }
        if self.planning_constraints is not None:
            schema["planning_constraints"] = self.planning_constraints
        return schema


class UnknownToolError(LookupError):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition[Any, Any]] = {}

    def register(self, definition: ToolDefinition[Any, Any]) -> None:
        if definition.name in self._tools:
            raise ValueError(f"duplicate tool: {definition.name}")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition[Any, Any]:
        try:
            return self._tools[name]
        except KeyError as error:
            raise UnknownToolError(name) from error

    def names(self, *, source: ToolSource | None = None) -> frozenset[str]:
        return frozenset(
            name
            for name, definition in self._tools.items()
            if source is None or definition.source is source
        )

    def catalog(self, allowed: frozenset[str]) -> tuple[dict[str, Any], ...]:
        return tuple(self.get(name).planning_schema() for name in sorted(allowed))

    def model_mcp_tools(
        self,
        allowed: frozenset[str],
        *,
        maximum_risk: RiskLevel = RiskLevel.LOW,
    ) -> tuple[ToolDefinition[Any, Any], ...]:
        risk_order = {
            RiskLevel.LOW: 0,
            RiskLevel.MEDIUM: 1,
            RiskLevel.HIGH: 2,
        }
        limit = risk_order[maximum_risk]
        return tuple(
            definition
            for name in sorted(allowed & self.names(source=ToolSource.MCP))
            if (definition := self.get(name)).source is ToolSource.MCP
            and risk_order[definition.risk] <= limit
        )
