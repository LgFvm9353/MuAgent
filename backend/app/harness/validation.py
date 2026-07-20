from pydantic import BaseModel

from app.contracts.execution import ExecutionPlan
from app.contracts.task import RiskLevel, TaskContract
from app.tools.registry import ToolRegistry


class SemanticValidationError(ValueError):
    pass


def parse_output(model: type[BaseModel], value: object) -> BaseModel:
    return model.model_validate(value)


def validate_plan(
    plan: ExecutionPlan,
    task: TaskContract,
    tools: ToolRegistry,
    *,
    workspace_files: frozenset[str] | None = None,
) -> None:
    if plan.task_id != task.task_id:
        raise SemanticValidationError("plan task ID does not match")
    if len(plan.steps) > task.budget.max_execution_steps:
        raise SemanticValidationError("plan exceeds execution step budget")
    available_files = set(workspace_files) if workspace_files is not None else None
    for step in plan.steps:
        if step.tool_name not in task.allowed_tools or step.tool_name in task.denied_tools:
            raise SemanticValidationError(f"tool is not allowed: {step.tool_name}")
        definition = tools.get(step.tool_name)
        try:
            validated_arguments = definition.input_model.model_validate(step.arguments)
            if definition.validate_input is not None:
                definition.validate_input(validated_arguments)
        except ValueError as error:
            raise SemanticValidationError(
                f"invalid arguments for {step.tool_name}: {error}"
            ) from error
        if step.risk != definition.risk:
            raise SemanticValidationError(f"risk mismatch for {step.tool_name}")
        if step.risk is RiskLevel.HIGH and not step.verification_method.strip():
            raise SemanticValidationError("high-risk step requires verification")
        if available_files is None:
            continue
        path = step.arguments.get("path")
        if not isinstance(path, str):
            continue
        if step.tool_name in {"read_workspace_file", "modify_workspace_file"}:
            if path not in available_files:
                raise SemanticValidationError(f"file is not available: {path}")
        elif step.tool_name == "create_workspace_file":
            if path in available_files:
                raise SemanticValidationError(f"file already exists: {path}")
            available_files.add(path)
