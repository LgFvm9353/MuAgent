from uuid import uuid4

from app.contracts.execution import ExecutionPlan, ExecutionStep
from app.contracts.task import RiskLevel
from app.tools.policy import ToolPolicy
from app.tools.registry import ToolDefinition, ToolRegistry
from app.contracts.base import ContractModel


class Empty(ContractModel):
    pass


async def handler(_: Empty) -> Empty:
    return Empty()


def test_high_risk_tool_requires_exact_confirmation() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="overwrite",
            description="overwrite",
            input_model=Empty,
            output_model=Empty,
            risk=RiskLevel.HIGH,
            timeout_seconds=1,
            idempotent=False,
            max_output_bytes=100,
            handler=handler,
        )
    )
    task_id = uuid4()
    plan = ExecutionPlan(
        plan_id=uuid4(),
        task_id=task_id,
        version=2,
        steps=(
            ExecutionStep(
                step_id="write",
                tool_name="overwrite",
                arguments={},
                risk=RiskLevel.HIGH,
                expected_result="file overwritten",
                verification_method="hash",
            ),
        ),
    )
    requirements = ToolPolicy(registry).confirmations(plan)
    assert len(requirements) == 1
    assert requirements[0].plan_version == 2
    assert len(requirements[0].call_hash) == 64
