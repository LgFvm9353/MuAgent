from time import monotonic

from pydantic import ValidationError

from app.contracts.task import RiskLevel
from app.tools.contracts import (
    ToolInvocation,
    ToolInvocationResult,
    normalized_arguments_digest,
)
from app.tools.registry import ToolRegistry, UnknownToolError


class ToolRuntimeError(ValueError):
    code = "tool_runtime_error"


class ToolNotAllowedError(ToolRuntimeError):
    code = "tool_not_allowed"


class ToolInputError(ToolRuntimeError):
    code = "tool_input_invalid"


class ToolOutputError(ToolRuntimeError):
    code = "tool_output_invalid"


class ToolOutputTooLargeError(ToolRuntimeError):
    code = "tool_output_too_large"


class ToolTimedOutError(ToolRuntimeError):
    code = "tool_timed_out"


_RISK_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
}


def effective_risk(registered: RiskLevel, requested: RiskLevel | None) -> RiskLevel:
    if requested is None or _RISK_ORDER[registered] >= _RISK_ORDER[requested]:
        return registered
    return requested


class ToolRuntime:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def invoke(self, invocation: ToolInvocation) -> ToolInvocationResult:
        try:
            definition = self._registry.get(invocation.tool_name)
        except UnknownToolError:
            raise
        allowed = invocation.context.allowed_tools
        if allowed is not None and not {
            definition.name,
            definition.canonical_tool_id,
        }.intersection(allowed):
            raise ToolNotAllowedError(definition.canonical_tool_id)

        try:
            request = definition.input_model.model_validate(invocation.arguments)
            if definition.validate_input is not None:
                definition.validate_input(request)
        except (ValidationError, ValueError, TypeError) as error:
            raise ToolInputError(f"tool input invalid: {error}") from error

        started = monotonic()
        output = await definition.handler(request)

        try:
            validated = definition.output_model.model_validate(output)
        except ValidationError as error:
            raise ToolOutputError(definition.canonical_tool_id) from error
        serialized = validated.model_dump_json()
        if len(serialized.encode()) > definition.max_output_bytes:
            raise ToolOutputTooLargeError("tool output size limit exceeded")

        return ToolInvocationResult(
            canonical_tool_id=definition.canonical_tool_id,
            source=definition.source,
            risk=effective_risk(definition.risk, invocation.requested_risk),
            output=validated,
            serialized_output=serialized,
            arguments_digest=normalized_arguments_digest(
                request.model_dump(mode="json", round_trip=True)
            ),
            duration_ms=int((monotonic() - started) * 1000),
            idempotent=definition.idempotent,
        )
