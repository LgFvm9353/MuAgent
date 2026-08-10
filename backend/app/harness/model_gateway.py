import asyncio
import json
from dataclasses import dataclass
from time import monotonic
from typing import Any, TypeVar, cast

import anthropic
from pydantic import BaseModel

from app.agent_loop.messages import ToolCall, ToolResult
from app.agent_loop.providers import ModelTurn, ModelTurnProvider, TextDeltaSink

OutputT = TypeVar("OutputT", bound=BaseModel)


class ModelGatewayError(RuntimeError):
    retryable: bool = False


class RetryableModelError(ModelGatewayError):
    retryable = True


class PermanentModelError(ModelGatewayError):
    pass


@dataclass(frozen=True, slots=True)
class ModelUsage:
    request_id: str | None
    model: str
    stop_reason: str | None
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    latency_ms: int
    retry_count: int

    @property
    def total_input_tokens(self) -> int:
        return self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens


@dataclass(frozen=True, slots=True)
class ModelResult:
    content: tuple[Any, ...]
    parsed_output: BaseModel | None
    usage: ModelUsage


class AnthropicModelProvider(ModelTurnProvider):
    """One-turn Anthropic adapter; AgentLoop owns all continuation decisions."""

    def __init__(self, gateway: "ModelGateway") -> None:
        self._gateway = gateway

    async def turn(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: tuple[dict[str, Any], ...],
        max_tokens: int,
        effort: str,
        on_text_delta: TextDeltaSink | None = None,
    ) -> ModelTurn:
        result = await self._gateway.streaming(
            model=model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            effort=effort,
            on_text_delta=on_text_delta,
        )
        calls: list[ToolCall] = []
        for block in result.content:
            if getattr(block, "type", None) == "tool_use":
                arguments = getattr(block, "input", None)
                calls.append(
                    ToolCall(
                        str(block.id),
                        str(block.name),
                        arguments if isinstance(arguments, dict) else None,
                    )
                )
        assistant = [self._gateway._serialize_block(block) for block in result.content]
        return ModelTurn(
            tuple(result.content),
            result.usage.stop_reason or "end_turn",
            tuple(calls),
            result.usage,
            {"role": "assistant", "content": assistant},
        )

    def tool_result_messages(self, results: tuple[ToolResult, ...]) -> list[dict[str, Any]]:
        return [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": item.call_id,
                        "is_error": item.is_error,
                        "content": json.dumps(item.content, ensure_ascii=False, sort_keys=True),
                    }
                    for item in results
                ],
            }
        ]


class ModelGateway:
    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        *,
        concurrency: int,
        timeout_seconds: float,
        max_retries: int = 8,
    ) -> None:
        self._client = client
        self._semaphore = asyncio.Semaphore(concurrency)
        self._timeout = timeout_seconds
        self._max_retries = max_retries

    def model_turn_provider(self) -> AnthropicModelProvider:
        return AnthropicModelProvider(self)

    async def structured(
        self,
        *,
        model: str,
        system: str,
        user_content: str,
        output_model: type[OutputT],
        max_tokens: int = 16_000,
        effort: str = "high",
    ) -> ModelResult:
        started = monotonic()
        response: Any | None = None
        attempt = 0
        for attempt in range(self._max_retries + 1):
            try:
                async with (
                    self._semaphore,
                    asyncio.timeout(max(0.001, self._timeout - (monotonic() - started))),
                ):
                    response = await self._client.messages.parse(
                        model=model,
                        max_tokens=max_tokens,
                        system=system,
                        messages=[{"role": "user", "content": user_content}],
                        output_format=output_model,
                        thinking={"type": "adaptive"},
                        output_config=cast(Any, {"effort": effort}),
                    )
                break
            except Exception as error:
                classified = self._classify(error)
                if (
                    not classified.retryable
                    or attempt >= self._max_retries
                    or monotonic() >= started + self._timeout
                ):
                    raise classified from error
                await asyncio.sleep(min(2**attempt, 8))
        if response is None:
            raise PermanentModelError("model request completed without a response")
        self._validate_stop_reason(response.stop_reason)
        return ModelResult(
            content=tuple(response.content),
            parsed_output=response.parsed_output,
            usage=self._usage(response, started, retry_count=attempt),
        )

    async def streaming(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: tuple[dict[str, Any], ...] = (),
        max_tokens: int = 64_000,
        effort: str = "high",
        on_text_delta: TextDeltaSink | None = None,
    ) -> ModelResult:
        started = monotonic()
        response: Any | None = None
        attempt = 0
        for attempt in range(self._max_retries + 1):
            try:
                async with (
                    self._semaphore,
                    asyncio.timeout(max(0.001, self._timeout - (monotonic() - started))),
                ):
                    async with self._client.messages.stream(
                        model=model,
                        max_tokens=max_tokens,
                        system=system,
                        messages=cast(Any, messages),
                        tools=cast(Any, list(tools)),
                        thinking={"type": "adaptive"},
                        output_config=cast(Any, {"effort": effort}),
                    ) as stream:
                        if on_text_delta is not None:
                            async for text in stream.text_stream:
                                if text:
                                    result = on_text_delta(text)
                                    if asyncio.iscoroutine(result):
                                        await result
                        response = await stream.get_final_message()
                break
            except Exception as error:
                classified = self._classify(error)
                if (
                    not classified.retryable
                    or attempt >= self._max_retries
                    or monotonic() >= started + self._timeout
                ):
                    raise classified from error
                await asyncio.sleep(min(2**attempt, 8))
        if response is None:
            raise PermanentModelError("model request completed without a response")
        self._validate_stop_reason(response.stop_reason)
        return ModelResult(
            content=tuple(response.content),
            parsed_output=None,
            usage=self._usage(response, started, retry_count=attempt),
        )

    @staticmethod
    def _serialize_block(block: Any) -> dict[str, Any]:
        if hasattr(block, "model_dump"):
            value = block.model_dump(mode="json")
            if isinstance(value, dict):
                return value
        raise PermanentModelError("unsupported response content block")

    @staticmethod
    def _merge_usage(current: ModelUsage | None, incoming: ModelUsage) -> ModelUsage:
        if current is None:
            return incoming
        return ModelUsage(
            request_id=incoming.request_id,
            model=incoming.model,
            stop_reason=incoming.stop_reason,
            input_tokens=current.input_tokens + incoming.input_tokens,
            output_tokens=current.output_tokens + incoming.output_tokens,
            cache_creation_input_tokens=(
                current.cache_creation_input_tokens + incoming.cache_creation_input_tokens
            ),
            cache_read_input_tokens=current.cache_read_input_tokens
            + incoming.cache_read_input_tokens,
            latency_ms=current.latency_ms + incoming.latency_ms,
            retry_count=current.retry_count + incoming.retry_count,
        )

    @staticmethod
    def _validate_stop_reason(stop_reason: str | None) -> None:
        if stop_reason in {"refusal", "max_tokens", "stop_sequence"}:
            raise PermanentModelError(f"model stopped with {stop_reason}")
        if stop_reason not in {"end_turn", "tool_use", "pause_turn"}:
            raise PermanentModelError(f"unsupported stop reason: {stop_reason}")

    @staticmethod
    def _classify(error: Exception) -> ModelGatewayError:
        if isinstance(
            error,
            (anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.RateLimitError),
        ):
            return RetryableModelError(type(error).__name__)
        if isinstance(error, anthropic.APIStatusError) and error.status_code >= 500:
            return RetryableModelError(type(error).__name__)
        if isinstance(
            error,
            (
                anthropic.BadRequestError,
                anthropic.AuthenticationError,
                anthropic.PermissionDeniedError,
                anthropic.NotFoundError,
            ),
        ):
            return PermanentModelError(type(error).__name__)
        return PermanentModelError(type(error).__name__)

    @staticmethod
    def _usage(response: Any, started: float, *, retry_count: int) -> ModelUsage:
        usage = response.usage
        return ModelUsage(
            request_id=getattr(response, "_request_id", None),
            model=response.model,
            stop_reason=response.stop_reason,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            latency_ms=int((monotonic() - started) * 1000),
            retry_count=retry_count,
        )
