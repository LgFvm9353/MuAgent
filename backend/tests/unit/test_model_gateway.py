from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from app.harness.model_gateway import ModelGateway, PermanentModelError
from app.harness.openai_gateway import OpenAIModelGateway


class StructuredOutput(BaseModel):
    answer: str


@pytest.mark.asyncio
async def test_openai_gateway_includes_schema_in_prompt_without_response_format() -> None:
    create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content='{"answer":"ok"}'),
                )
            ],
            usage=None,
            model="gpt-5.6-sol",
        )
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    gateway = OpenAIModelGateway(
        client,  # type: ignore[arg-type]
        concurrency=1,
        timeout_seconds=10,
    )

    result = await gateway.structured(
        model="gpt-5.6-sol",
        system="Return a structured answer.",
        user_content="Hello",
        output_model=StructuredOutput,
    )

    request = create.await_args.kwargs
    system_prompt = request["messages"][0]["content"]
    assert result.parsed_output == StructuredOutput(answer="ok")
    assert "response_format" not in request
    assert "JSON Schema" in system_prompt
    assert '"answer"' in system_prompt
    assert "不要输出 Markdown" in system_prompt


@pytest.mark.parametrize("reason", ["refusal", "max_tokens", "stop_sequence", None])
def test_non_success_stop_reasons_are_rejected(reason: str | None) -> None:
    with pytest.raises(PermanentModelError):
        ModelGateway._validate_stop_reason(reason)


@pytest.mark.parametrize("reason", ["end_turn", "tool_use", "pause_turn"])
def test_supported_stop_reasons(reason: str) -> None:
    ModelGateway._validate_stop_reason(reason)
