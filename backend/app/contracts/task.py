from enum import StrEnum
from uuid import UUID

from pydantic import Field

from app.contracts.base import ContractModel


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AcceptanceCriterion(ContractModel):
    description: str = Field(min_length=1)
    verification_method: str = Field(min_length=1)


class BudgetLimits(ContractModel):
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
    failure_policy: str = Field(min_length=1)
