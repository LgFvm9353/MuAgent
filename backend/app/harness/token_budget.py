import json
from dataclasses import dataclass
from typing import Any

from app.harness.model_capabilities import ModelCapability


class ConservativeTokenCounter:
    name = "utf8-conservative-v1"

    def count_text(self, value: str) -> int:
        if not value:
            return 0
        # One token per two UTF-8 bytes intentionally overestimates most prose while
        # remaining safe for Chinese, source code, and compact JSON.
        return max(1, (len(value.encode("utf-8")) + 1) // 2)

    def count_json(self, value: Any) -> int:
        return self.count_text(
            json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        )


@dataclass(frozen=True, slots=True)
class ContextBudget:
    context_window: int
    estimated_input_tokens: int
    reserved_output_tokens: int
    safety_margin_tokens: int
    maximum_input_tokens: int
    utilization: float

    @property
    def exceeded(self) -> bool:
        return self.estimated_input_tokens > self.maximum_input_tokens


def calculate_budget(
    capability: ModelCapability,
    estimated_input_tokens: int,
    *,
    requested_output_tokens: int,
    safety_margin_ratio: float,
) -> ContextBudget:
    reserved_output = min(requested_output_tokens, capability.max_output_tokens)
    safety_margin = max(1_024, int(capability.context_window * safety_margin_ratio))
    maximum_input = max(1, capability.context_window - reserved_output - safety_margin)
    return ContextBudget(
        context_window=capability.context_window,
        estimated_input_tokens=estimated_input_tokens,
        reserved_output_tokens=reserved_output,
        safety_margin_tokens=safety_margin,
        maximum_input_tokens=maximum_input,
        utilization=estimated_input_tokens / maximum_input,
    )
