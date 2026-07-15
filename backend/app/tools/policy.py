import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from app.contracts.execution import ExecutionPlan, ExecutionStep
from app.contracts.task import RiskLevel
from app.tools.registry import ToolRegistry


@dataclass(frozen=True, slots=True)
class ConfirmationRequirement:
    task_id: UUID
    plan_id: UUID
    plan_version: int
    step_id: str
    tool_name: str
    arguments: dict[str, object]
    impact: str
    risk: RiskLevel
    call_hash: str


def call_hash(plan: ExecutionPlan, step: ExecutionStep) -> str:
    payload = {
        "task_id": str(plan.task_id),
        "plan_id": str(plan.plan_id),
        "plan_version": plan.version,
        "step_id": step.step_id,
        "tool": step.tool_name,
        "arguments": step.arguments,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ToolPolicy:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def confirmations(self, plan: ExecutionPlan) -> tuple[ConfirmationRequirement, ...]:
        required: list[ConfirmationRequirement] = []
        for step in plan.steps:
            definition = self._registry.get(step.tool_name)
            if definition.risk is not RiskLevel.HIGH:
                continue
            required.append(
                ConfirmationRequirement(
                    task_id=plan.task_id,
                    plan_id=plan.plan_id,
                    plan_version=plan.version,
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                    arguments=step.arguments,
                    impact=step.expected_result,
                    risk=definition.risk,
                    call_hash=call_hash(plan, step),
                )
            )
        return tuple(required)
