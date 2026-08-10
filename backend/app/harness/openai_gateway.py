import asyncio
import json
import re
from dataclasses import dataclass
from hashlib import sha256
from time import monotonic
from types import SimpleNamespace
from typing import Any, TypeVar, cast

import openai
from pydantic import BaseModel

from app.agent_loop import ModelTurn, ModelTurnProvider, TextDeltaSink, ToolCall, ToolResult
from app.harness.model_gateway import (
    ModelGatewayError,
    ModelResult,
    ModelUsage,
    PermanentModelError,
    RetryableModelError,
)
from app.harness.structured_tools import parse_structured_output, structured_output_system
from app.logging import logger

OutputT = TypeVar("OutputT", bound=BaseModel)

_PROVIDER_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_PROVIDER_TOOL_NAME_INVALID = re.compile(r"[^A-Za-z0-9_-]+")
_PROVIDER_TOOL_NAME_MAX_LENGTH = 64
_PROVIDER_TOOL_NAME_HASH_LENGTH = 12
_PROVIDER_ERROR_MESSAGE_MAX_LENGTH = 500


@dataclass(frozen=True, slots=True)
class _StreamToolCall:
    id: str
    name: str
    arguments: str

    @property
    def function(self) -> SimpleNamespace:
        return SimpleNamespace(name=self.name, arguments=self.arguments)

    def model_dump(self, **_: Any) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


def _provider_tool_name(canonical_name: str) -> str:
    readable = _PROVIDER_TOOL_NAME_INVALID.sub("_", canonical_name).strip("_-") or "tool"
    digest = sha256(canonical_name.encode("utf-8")).hexdigest()[:_PROVIDER_TOOL_NAME_HASH_LENGTH]
    readable_limit = _PROVIDER_TOOL_NAME_MAX_LENGTH - len(digest) - 1
    alias = f"{readable[:readable_limit]}_{digest}"
    if not _PROVIDER_TOOL_NAME_PATTERN.fullmatch(alias):
        raise PermanentModelError("invalid_provider_tool_name")
    return alias


class OpenAIModelProvider(ModelTurnProvider):
    """One-turn OpenAI adapter consumed by AgentLoop."""

    def __init__(self, gateway: "OpenAIModelGateway") -> None:
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
        del effort
        provider_tools: list[dict[str, Any]] = []
        mapping: dict[str, str] = {}
        canonical_names: set[str] = set()
        for tool in tools:
            canonical = tool["name"]
            if not isinstance(canonical, str) or not canonical:
                raise PermanentModelError("invalid_canonical_tool_name")
            if canonical in canonical_names:
                raise PermanentModelError("duplicate_canonical_tool_name")
            canonical_names.add(canonical)
            provider_name = _provider_tool_name(canonical)
            if provider_name in mapping:
                raise PermanentModelError("provider_tool_name_collision")
            mapping[provider_name] = canonical
            provider_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": provider_name,
                        "description": tool["description"],
                        "parameters": tool.get("input_schema")
                        or tool.get("parameters")
                        or {"type": "object"},
                    },
                }
            )
        request_messages = list(messages)
        if not request_messages or request_messages[0].get("role") != "system":
            request_messages.insert(0, {"role": "system", "content": system})
        result, message = await self._gateway.model_turn(
            model=model,
            messages=request_messages,
            tools=tuple(provider_tools),
            max_tokens=max_tokens,
            on_text_delta=on_text_delta,
        )
        calls: list[ToolCall] = []
        for call in tuple(message.tool_calls or ()):
            canonical = mapping.get(call.function.name, call.function.name)
            error_code = None if call.function.name in mapping else "unknown_provider_tool"
            try:
                arguments = json.loads(call.function.arguments)
            except (json.JSONDecodeError, TypeError):
                arguments = None
            calls.append(
                ToolCall(
                    str(call.id),
                    canonical,
                    arguments if isinstance(arguments, dict) else None,
                    error_code,
                )
            )
        assistant: dict[str, Any] = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            assistant["tool_calls"] = [
                call.model_dump(mode="json") for call in tuple(message.tool_calls)
            ]
        return ModelTurn(
            message.content or "",
            "tool_calls" if calls else "stop",
            tuple(calls),
            result.usage,
            assistant,
        )

    def tool_result_messages(self, results: tuple[ToolResult, ...]) -> list[dict[str, Any]]:
        return [
            {
                "role": "tool",
                "tool_call_id": item.call_id,
                "content": json.dumps(item.content, ensure_ascii=False, sort_keys=True),
            }
            for item in results
        ]


class OpenAIModelGateway:
    def __init__(
        self,
        client: openai.AsyncOpenAI,
        *,
        concurrency: int,
        timeout_seconds: float,
        max_retries: int = 2,
    ) -> None:
        self._client = client
        self._semaphore = asyncio.Semaphore(concurrency)
        self._timeout = timeout_seconds
        self._max_retries = max_retries

    def model_turn_provider(self) -> OpenAIModelProvider:
        return OpenAIModelProvider(self)

    async def structured(
        self,
        *,
        model: str,
        system: str,
        user_content: str,
        output_model: type[OutputT],
        max_tokens: int = 4_096,
        effort: str = "high",
    ) -> ModelResult:
        del effort
        structured_system = structured_output_system(system, output_model)
        started = monotonic()
        response: Any | None = None
        attempt = 0
        for attempt in range(self._max_retries + 1):
            try:
                async with (
                    self._semaphore,
                    asyncio.timeout(max(0.001, self._timeout - (monotonic() - started))),
                ):
                    response = await self._client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": structured_system},
                            {"role": "user", "content": user_content},
                        ],
                        max_completion_tokens=max_tokens,
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

        if response is None or not response.choices:
            raise PermanentModelError("empty_model_response")
        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise PermanentModelError("model_output_truncated")
        if choice.finish_reason not in {"stop", "tool_calls"}:
            raise PermanentModelError("unsupported_stop_reason")
        content = choice.message.content
        if not content:
            raise PermanentModelError("empty_structured_output")
        parsed = parse_structured_output(content, output_model)

        usage = response.usage
        return ModelResult(
            content=(),
            parsed_output=parsed,
            usage=ModelUsage(
                request_id=getattr(response, "_request_id", None),
                model=response.model,
                stop_reason=choice.finish_reason,
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
                latency_ms=int((monotonic() - started) * 1000),
                retry_count=attempt,
            ),
        )

    async def model_turn(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: tuple[dict[str, Any], ...],
        max_tokens: int,
        on_text_delta: TextDeltaSink | None = None,
    ) -> tuple[ModelResult, Any]:
        started = monotonic()
        response: Any | None = None
        attempt = 0
        for attempt in range(self._max_retries + 1):
            try:
                async with (
                    self._semaphore,
                    asyncio.timeout(max(0.001, self._timeout - (monotonic() - started))),
                ):
                    if on_text_delta is None:
                        response = await self._client.chat.completions.create(
                            model=model,
                            messages=cast(Any, messages),
                            tools=cast(Any, tools),
                            max_completion_tokens=max_tokens,
                        )
                    else:
                        response = await self._stream_model_turn(
                            model=model,
                            messages=messages,
                            tools=tools,
                            max_tokens=max_tokens,
                            on_text_delta=on_text_delta,
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
        if response is None or not response.choices:
            raise PermanentModelError("empty_model_response")
        choice = response.choices[0]
        if choice.finish_reason not in {"stop", "tool_calls"}:
            raise PermanentModelError("unsupported_stop_reason")
        calls = tuple(choice.message.tool_calls or ())
        if choice.finish_reason == "tool_calls" and not calls:
            raise PermanentModelError("tool_calls_missing")
        usage = response.usage
        result = ModelResult(
            content=(),
            parsed_output=None,
            usage=ModelUsage(
                request_id=getattr(response, "_request_id", None),
                model=response.model,
                stop_reason=choice.finish_reason,
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
                latency_ms=int((monotonic() - started) * 1000),
                retry_count=attempt,
            ),
        )
        return result, choice.message

    async def _stream_model_turn(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: tuple[dict[str, Any], ...],
        max_tokens: int,
        on_text_delta: TextDeltaSink,
    ) -> Any:
        stream = await self._client.chat.completions.create(
            model=model,
            messages=cast(Any, messages),
            tools=cast(Any, tools),
            max_completion_tokens=max_tokens,
            stream=True,
        )
        content_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        usage: Any | None = None
        request_id: str | None = None
        async for chunk in stream:
            request_id = request_id or getattr(chunk, "id", None)
            usage = getattr(chunk, "usage", None) or usage
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            finish_reason = getattr(choice, "finish_reason", None) or finish_reason
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue
            text = getattr(delta, "content", None)
            if text:
                content_parts.append(text)
                result = on_text_delta(text)
                if asyncio.iscoroutine(result):
                    await result
            for part in getattr(delta, "tool_calls", None) or ():
                index = int(getattr(part, "index", 0) or 0)
                item = tool_calls.setdefault(
                    index,
                    {
                        "id": getattr(part, "id", None) or f"stream-call-{index}",
                        "name": "",
                        "arguments": "",
                    },
                )
                if getattr(part, "id", None):
                    item["id"] = part.id
                function = getattr(part, "function", None)
                if function is not None:
                    item["name"] += getattr(function, "name", None) or ""
                    item["arguments"] += getattr(function, "arguments", None) or ""

        calls = tuple(
            _StreamToolCall(item["id"], item["name"], item["arguments"])
            for _, item in sorted(tool_calls.items())
        )
        message = SimpleNamespace(content="".join(content_parts), tool_calls=calls)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=message,
                    finish_reason=finish_reason or ("tool_calls" if calls else "stop"),
                )
            ],
            usage=usage or SimpleNamespace(prompt_tokens=0, completion_tokens=0),
            model=model,
            _request_id=request_id,
        )

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
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
            latency_ms=current.latency_ms + incoming.latency_ms,
            retry_count=current.retry_count + incoming.retry_count,
        )

    @staticmethod
    def _log_bad_request(error: openai.BadRequestError) -> None:
        body: Any = error.body
        details: Any = body
        if isinstance(body, dict):
            nested = body.get("error")
            if isinstance(nested, dict):
                details = nested
        provider_code = details.get("code") if isinstance(details, dict) else None
        provider_param = details.get("param") if isinstance(details, dict) else None
        provider_message = details.get("message") if isinstance(details, dict) else None
        if not isinstance(provider_message, str):
            provider_message = str(provider_message or "provider rejected request")
        logger().warning(
            "provider_request_rejected",
            status_code=error.status_code,
            provider_code=provider_code if isinstance(provider_code, str) else None,
            provider_param=provider_param if isinstance(provider_param, str) else None,
            provider_message=provider_message[:_PROVIDER_ERROR_MESSAGE_MAX_LENGTH],
            request_id=getattr(error, "request_id", None),
        )

    @staticmethod
    def _classify(error: Exception) -> ModelGatewayError:
        if isinstance(
            error,
            (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError),
        ):
            return RetryableModelError(type(error).__name__)
        if isinstance(error, openai.APIStatusError) and error.status_code >= 500:
            return RetryableModelError(type(error).__name__)
        if isinstance(error, openai.AuthenticationError):
            return PermanentModelError("authentication_failed")
        if isinstance(error, openai.NotFoundError):
            return PermanentModelError("model_not_found")
        if isinstance(error, openai.PermissionDeniedError):
            return PermanentModelError("permission_denied")
        if isinstance(error, openai.BadRequestError):
            OpenAIModelGateway._log_bad_request(error)
            return PermanentModelError("invalid_provider_request")
        return PermanentModelError(type(error).__name__)
