import asyncio
import json
from dataclasses import dataclass
from time import monotonic
from typing import Any, Protocol, TypeVar, cast

import anthropic
from pydantic import BaseModel

from app.harness.structured_tools import (
    anthropic_text,
    parse_structured_output,
    structured_output_system,
)

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


class ModelToolCallPort(Protocol):
    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class ModelGateway:
    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        *,
        concurrency: int,
        timeout_seconds: float,
        max_continuations: int = 3,
        max_retries: int = 2,
    ) -> None:
        self._client = client
        self._semaphore = asyncio.Semaphore(concurrency)
        self._timeout = timeout_seconds
        self._max_continuations = max_continuations
        self._max_retries = max_retries

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

    async def structured_with_tools(
        self,
        *,
        model: str,
        system: str,
        user_content: str,
        output_model: type[OutputT],
        tools: tuple[dict[str, Any], ...],
        executor: ModelToolCallPort,
        max_tool_rounds: int = 6,
        max_tokens: int = 16_000,
        effort: str = "high",
    ) -> ModelResult:
        if not tools:
            return await self.structured(
                model=model,
                system=system,
                user_content=user_content,
                output_model=output_model,
                max_tokens=max_tokens,
                effort=effort,
            )
        result = await self.tool_loop(
            model=model,
            system=structured_output_system(system, output_model),
            messages=[{"role": "user", "content": user_content}],
            tools=tools,
            executor=executor,
            max_tool_rounds=max_tool_rounds,
            max_tokens=max_tokens,
            effort=effort,
        )
        parsed = parse_structured_output(anthropic_text(result.content), output_model)
        return ModelResult(result.content, parsed, result.usage)

    async def streaming(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: tuple[dict[str, Any], ...] = (),
        max_tokens: int = 64_000,
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
                    async with self._client.messages.stream(
                        model=model,
                        max_tokens=max_tokens,
                        system=system,
                        messages=cast(Any, messages),
                        tools=cast(Any, list(tools)),
                        thinking={"type": "adaptive"},
                        output_config=cast(Any, {"effort": effort}),
                    ) as stream:
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

    async def tool_loop(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: tuple[dict[str, Any], ...],
        executor: ModelToolCallPort,
        max_tool_rounds: int = 10,
        max_tokens: int = 64_000,
        effort: str = "high",
    ) -> ModelResult:
        conversation = list(messages)
        pause_count = 0
        tool_rounds = 0
        aggregate: ModelUsage | None = None
        while tool_rounds <= max_tool_rounds:
            result = await self.streaming(
                model=model,
                system=system,
                messages=conversation,
                tools=tools,
                max_tokens=max_tokens,
                effort=effort,
            )
            aggregate = self._merge_usage(aggregate, result.usage)
            stop_reason = result.usage.stop_reason
            if stop_reason == "end_turn":
                return ModelResult(result.content, result.parsed_output, aggregate)
            assistant_content = [self._serialize_block(block) for block in result.content]
            conversation.append({"role": "assistant", "content": assistant_content})
            if stop_reason == "pause_turn":
                pause_count += 1
                if pause_count > self._max_continuations:
                    raise PermanentModelError("pause_turn continuation limit exceeded")
                conversation.append({"role": "user", "content": "Continue the previous response."})
                continue
            tool_uses = [
                block for block in result.content if getattr(block, "type", None) == "tool_use"
            ]
            if not tool_uses:
                raise PermanentModelError("tool_use stop reason contained no tool calls")
            tool_rounds += 1
            if tool_rounds > max_tool_rounds:
                raise PermanentModelError("tool loop round limit exceeded")

            async def execute(block: Any) -> dict[str, Any]:
                tool_use_id = str(block.id)
                name = str(block.name)
                arguments = getattr(block, "input", None)
                if not isinstance(arguments, dict):
                    return {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "is_error": True,
                        "content": "Tool arguments were not an object.",
                    }
                try:
                    output = await executor.execute(name, arguments)
                    return {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": json.dumps(output, ensure_ascii=False, sort_keys=True),
                    }
                except Exception as error:
                    return {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "is_error": True,
                        "content": f"Tool failed: {type(error).__name__}",
                    }

            results = [await execute(block) for block in tool_uses]
            conversation.append({"role": "user", "content": results})
        raise PermanentModelError("tool loop round limit exceeded")

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
