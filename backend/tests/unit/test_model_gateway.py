import pytest

from app.harness.model_gateway import ModelGateway, PermanentModelError


@pytest.mark.parametrize("reason", ["refusal", "max_tokens", "stop_sequence", None])
def test_non_success_stop_reasons_are_rejected(reason: str | None) -> None:
    with pytest.raises(PermanentModelError):
        ModelGateway._validate_stop_reason(reason)


@pytest.mark.parametrize("reason", ["end_turn", "tool_use", "pause_turn"])
def test_supported_stop_reasons(reason: str) -> None:
    ModelGateway._validate_stop_reason(reason)
