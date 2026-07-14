from pydantic import BaseModel

from app.contracts.execution import ExecutionPlan
from app.contracts.task import RiskLevel, TaskContract
from app.tools.registry import ToolRegistry


class SemanticValidationError(ValueError):
    pass


def parse_output(model: type[BaseModel], value: object) -> BaseModel:
    return model.model_validate(value)


def validate_plan(plan: ExecutionPlan, task: TaskContract, tools: ToolRegistry) -> None:
    if plan.task_id != task.task_id:
        raise SemanticValidationError("plan task ID does not match")
    if len(plan.steps) > task.budget.max_execution_steps:
        raise SemanticValidationError("plan exceeds execution step budget")
    for step in plan.steps:
        if step.tool_name not in task.allowed_tools or step.tool_name in task.denied_tools:
            raise SemanticValidationError(f"tool is not allowed: {step.tool_name}")
        definition = tools.get(step.tool_name)
        try:
            definition.input_model.model_validate(step.arguments)
        except ValueError as error:
            raise SemanticValidationError(f"invalid arguments for {step.tool_name}") from error
        if step.risk != definition.risk:
            raise SemanticValidationError(f"risk mismatch for {step.tool_name}")
        if step.risk is RiskLevel.HIGH and not step.verification_method.strip():
            raise SemanticValidationError("high-risk step requires verification")
