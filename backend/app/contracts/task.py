from enum import StrEnum
from pathlib import PurePosixPath
from uuid import UUID

from pydantic import Field, field_validator

from app.contracts.base import ContractModel


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AcceptanceCriterion(ContractModel):
    description: str = Field(min_length=1)
    verification_method: str = Field(min_length=1)


class BudgetLimits(ContractModel):
    max_deliberation_rounds: int = Field(default=3, ge=1, le=3)
    max_revisions: int = Field(default=2, ge=0, le=2)
    max_execution_steps: int = Field(default=20, ge=1, le=100)
    max_runtime_seconds: int = Field(default=3600, ge=1)
    max_tokens: int = Field(default=200_000, ge=1)
    max_cost_usd: float = Field(default=25.0, gt=0)


class TaskContract(ContractModel):
    task_id: UUID
    goal: str = Field(min_length=1, max_length=10_000)
    inputs: dict[str, str] = Field(default_factory=dict)
    constraints: tuple[str, ...] = ()
    acceptance_criteria: tuple[AcceptanceCriterion, ...] = Field(min_length=1)
    allowed_tools: frozenset[str]
    denied_tools: frozenset[str] = frozenset()
    budget: BudgetLimits = BudgetLimits()
    workspace_relative: str
    failure_policy: str = Field(min_length=1)

    @field_validator("workspace_relative")
    @classmethod
    def validate_workspace(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value in {"", "."}:
            raise ValueError("workspace path must be safe and relative")
        return value
