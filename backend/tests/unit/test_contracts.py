from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts.execution import ExecutionPlan, ExecutionStep
from app.contracts.task import AcceptanceCriterion, RiskLevel, TaskContract


def test_task_rejects_path_traversal() -> None:
    with pytest.raises(ValidationError):
        TaskContract(
            task_id=uuid4(),
            goal="goal",
            acceptance_criteria=(
                AcceptanceCriterion(description="done", verification_method="test"),
            ),
            allowed_tools=frozenset(),
            workspace_relative="../escape",
            failure_policy="fail",
        )


def test_execution_plan_rejects_cycle() -> None:
    steps = (
        ExecutionStep(
            step_id="a",
            depends_on=frozenset({"b"}),
            tool_name="read",
            arguments={},
            risk=RiskLevel.LOW,
            expected_result="a",
            verification_method="check",
        ),
        ExecutionStep(
            step_id="b",
            depends_on=frozenset({"a"}),
            tool_name="read",
            arguments={},
            risk=RiskLevel.LOW,
            expected_result="b",
            verification_method="check",
        ),
    )
    with pytest.raises(ValidationError):
        ExecutionPlan(plan_id=uuid4(), task_id=uuid4(), version=1, steps=steps)
