from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelCapability:
    context_window: int
    max_output_tokens: int
    tokenizer: str = "conservative"


_CAPABILITIES: dict[str, ModelCapability] = {
    "claude-opus-4-8": ModelCapability(1_000_000, 32_000),
    "claude-opus-4-7": ModelCapability(200_000, 32_000),
    "claude-sonnet-4-6": ModelCapability(1_000_000, 64_000),
    "gpt-5.6-sol": ModelCapability(1_000_000, 128_000),
}


class ModelCapabilityRegistry:
    def __init__(
        self,
        *,
        unknown_context_window: int = 128_000,
        unknown_max_output_tokens: int = 8_192,
        context_window_overrides: dict[str, int] | None = None,
        max_output_overrides: dict[str, int] | None = None,
    ) -> None:
        self._unknown = ModelCapability(
            unknown_context_window,
            unknown_max_output_tokens,
        )
        self._context_window_overrides = {
            key.casefold(): value for key, value in (context_window_overrides or {}).items()
        }
        self._max_output_overrides = {
            key.casefold(): value for key, value in (max_output_overrides or {}).items()
        }

    def resolve(
        self,
        model: str,
        *,
        context_window_override: int | None = None,
        max_output_tokens_override: int | None = None,
    ) -> ModelCapability:
        key = model.casefold()
        capability = _CAPABILITIES.get(key, self._unknown)
        return ModelCapability(
            context_window=(
                context_window_override
                or self._context_window_overrides.get(key)
                or capability.context_window
            ),
            max_output_tokens=(
                max_output_tokens_override
                or self._max_output_overrides.get(key)
                or capability.max_output_tokens
            ),
            tokenizer=capability.tokenizer,
        )
