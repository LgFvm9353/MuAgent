from dataclasses import dataclass
from enum import StrEnum

from app.contracts.task import BudgetLimits


class GuardDecision(StrEnum):
    ALLOW = "allow"
    CANCELLED = "cancelled"
    BUDGET_EXCEEDED = "budget_exceeded"


@dataclass(frozen=True, slots=True)
class BudgetUsage:
    revisions: int = 0
    execution_steps: int = 0
    runtime_seconds: float = 0
    tokens: int = 0
    cost_usd: float = 0


class BudgetGuard:
    def evaluate(
        self,
        limits: BudgetLimits,
        usage: BudgetUsage,
        *,
        cancel_requested: bool,
    ) -> GuardDecision:
        if cancel_requested:
            return GuardDecision.CANCELLED
        if (
            usage.revisions > limits.max_revisions
            or usage.execution_steps > limits.max_execution_steps
            or usage.runtime_seconds > limits.max_runtime_seconds
            or usage.tokens > limits.max_tokens
            or usage.cost_usd > limits.max_cost_usd
        ):
            return GuardDecision.BUDGET_EXCEEDED
        return GuardDecision.ALLOW
