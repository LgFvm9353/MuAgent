from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.contracts.task import RiskLevel


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

    def anthropic_schema(self) -> dict[str, Any]:
        schema = self.input_model.model_json_schema()
        schema["additionalProperties"] = False
        properties = schema.get("properties", {})
        schema["required"] = sorted(properties)
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
            "strict": True,
        }

    def planning_schema(self) -> dict[str, Any]:
        return {
            **self.anthropic_schema(),
            "risk": self.risk.value,
            "idempotent": self.idempotent,
        }


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

    def catalog(self, allowed: frozenset[str]) -> tuple[dict[str, Any], ...]:
        return tuple(self._tools[name].planning_schema() for name in sorted(allowed))
