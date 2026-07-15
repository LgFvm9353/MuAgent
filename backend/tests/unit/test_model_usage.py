from app.harness.model_gateway import ModelGateway, ModelUsage


def usage(*, input_tokens: int, output_tokens: int, retries: int) -> ModelUsage:
    return ModelUsage(
        request_id="request",
        model="claude-opus-4-8",
        stop_reason="tool_use",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=2,
        cache_read_input_tokens=3,
        latency_ms=10,
        retry_count=retries,
    )


def test_tool_loop_usage_is_accumulated() -> None:
    merged = ModelGateway._merge_usage(
        usage(input_tokens=5, output_tokens=7, retries=1),
        usage(input_tokens=11, output_tokens=13, retries=2),
    )
    assert merged.input_tokens == 16
    assert merged.output_tokens == 20
    assert merged.cache_creation_input_tokens == 4
    assert merged.cache_read_input_tokens == 6
    assert merged.latency_ms == 20
    assert merged.retry_count == 3
