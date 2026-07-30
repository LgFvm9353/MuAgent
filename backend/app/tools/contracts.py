import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.task import RiskLevel


class ToolSource(StrEnum):
    LOCAL = "local"
    MCP = "mcp"


class ToolOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    REJECTED = "rejected"
    OUTCOME_UNKNOWN = "outcome_unknown"


class ToolContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: UUID | None = None
    turn_id: UUID | None = None
    agent_run_id: UUID | None = None
    workspace_id: str | None = Field(default=None, max_length=255)
    allowed_tools: frozenset[str] | None = None


class ToolInvocation(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str = Field(min_length=1, max_length=255)
    arguments: dict[str, Any]
    context: ToolContext = ToolContext()
    requested_risk: RiskLevel | None = None


@dataclass(frozen=True, slots=True)
class ToolInvocationResult:
    canonical_tool_id: str
    source: ToolSource
    risk: RiskLevel
    output: BaseModel
    serialized_output: str
    arguments_digest: str
    duration_ms: int
    idempotent: bool
    metadata: dict[str, Any] = field(default_factory=dict)


def normalized_arguments_digest(arguments: dict[str, Any]) -> str:
    encoded = json.dumps(
        arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
