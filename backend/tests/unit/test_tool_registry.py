from app.contracts.base import ContractModel
from app.contracts.task import RiskLevel
from app.tools.registry import ToolDefinition


class Empty(ContractModel):
    pass


async def handler(_: Empty) -> Empty:
    return Empty()


def test_anthropic_tool_schema_is_strict() -> None:
    definition = ToolDefinition(
        name="safe",
        description="safe tool",
        input_model=Empty,
        output_model=Empty,
        risk=RiskLevel.LOW,
        timeout_seconds=1,
        idempotent=True,
        max_output_bytes=100,
        handler=handler,
    )
    schema = definition.anthropic_schema()
    assert schema["strict"] is True
    assert schema["input_schema"]["additionalProperties"] is False
