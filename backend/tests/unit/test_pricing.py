from decimal import Decimal

import pytest

from app.harness.pricing import estimate_cost


def test_estimate_cost_includes_cache_usage() -> None:
    cost = estimate_cost(
        "claude-opus-4-8",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation_input_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
    )
    assert cost == Decimal("36.75")


def test_unknown_model_price_is_rejected() -> None:
    with pytest.raises(ValueError):
        estimate_cost("unknown", input_tokens=1, output_tokens=1)
