import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Any, Protocol, TypeVar

import anthropic
from pydantic import BaseModel

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


class ToolExecutor(Protocol):
    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class ModelGateway:
    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        *,
        concurrency: int,
        timeout_seconds: float,
        max_continuations: int = 3,
    ) -> None:
        self._client = client
        self._semaphore = asyncio.Semaphore(concurrency)
        self._timeout = timeout_seconds
        self._max_continuations = max_continuations

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
        try:
            async with self._semaphore, asyncio.timeout(self._timeout):
                response = await self._client.messages.parse(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user_content}],
                    output_format=output_model,
                    thinking={"type": "adaptive"},
                    output_config={"effort": effort},
                )
        except Exception as error:
            raise self._classify(error) from error
        self._validate_stop_reason(response.stop_reason)
        return ModelResult(
            content=tuple(response.content),
            parsed_output=response.parsed_output,
            usage=self._usage(response, started, retry_count=0),
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
    ) -> ModelResult:
        started = monotonic()
        try:
            async with self._semaphore, asyncio.timeout(self._timeout):
                async with self._client.messages.stream(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=messages,
                    tools=list(tools),
                    thinking={"type": "adaptive"},
                    output_config={"effort": effort},
                ) as stream:
                    response = await stream.get_final_message()
        except Exception as error:
            raise self._classify(error) from error
        self._validate_stop_reason(response.stop_reason)
        return ModelResult(
            content=tuple(response.content),
            parsed_output=None,
            usage=self._usage(response, started, retry_count=0),
        )

    @staticmethod
    def _validate_stop_reason(stop_reason: str | None) -> None:
        if stop_reason in {"refusal", "max_tokens", "stop_sequence"}:
            raise PermanentModelError(f"model stopped with {stop_reason}")
        if stop_reason not in {"end_turn", "tool_use", "pause_turn"}:
            raise PermanentModelError(f"unsupported stop reason: {stop_reason}")

    @staticmethod
    def _classify(error: Exception) -> ModelGatewayError:
        if isinstance(error, (anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.RateLimitError)):
            return RetryableModelError(type(error).__name__)
        if isinstance(error, anthropic.APIStatusError) and error.status_code >= 500:
            return RetryableModelError(type(error).__name__)
        if isinstance(error, (anthropic.BadRequestError, anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError)):
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
