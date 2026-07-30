import asyncio
import json
import re
from hashlib import sha256
from time import monotonic
from typing import Any, TypeVar, cast

import openai
from pydantic import BaseModel

from app.harness.model_gateway import (
    ModelGatewayError,
    ModelResult,
    ModelToolCallPort,
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


def _provider_tool_name(canonical_name: str) -> str:
    readable = _PROVIDER_TOOL_NAME_INVALID.sub("_", canonical_name).strip("_-") or "tool"
    digest = sha256(canonical_name.encode("utf-8")).hexdigest()[:_PROVIDER_TOOL_NAME_HASH_LENGTH]
    readable_limit = _PROVIDER_TOOL_NAME_MAX_LENGTH - len(digest) - 1
    alias = f"{readable[:readable_limit]}_{digest}"
    if not _PROVIDER_TOOL_NAME_PATTERN.fullmatch(alias):
        raise PermanentModelError("invalid_provider_tool_name")
    return alias


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
        max_tokens: int = 4_096,
        effort: str = "high",
    ) -> ModelResult:
        del effort
        if not tools:
            return await self.structured(
                model=model,
                system=system,
                user_content=user_content,
                output_model=output_model,
                max_tokens=max_tokens,
            )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": structured_output_system(system, output_model)},
            {"role": "user", "content": user_content},
        ]
        canonical_names: set[str] = set()
        provider_to_canonical: dict[str, str] = {}
        openai_tools_list: list[dict[str, Any]] = []
        for tool in tools:
            canonical_name = tool["name"]
            if not isinstance(canonical_name, str) or not canonical_name:
                raise PermanentModelError("invalid_canonical_tool_name")
            if canonical_name in canonical_names:
                raise PermanentModelError("duplicate_canonical_tool_name")
            canonical_names.add(canonical_name)
            provider_name = _provider_tool_name(canonical_name)
            if provider_name in provider_to_canonical:
                raise PermanentModelError("provider_tool_name_collision")
            provider_to_canonical[provider_name] = canonical_name
            openai_tools_list.append(
                {
                    "type": "function",
                    "function": {
                        "name": provider_name,
                        "description": tool["description"],
                        "parameters": tool["input_schema"],
                    },
                }
            )
        openai_tools = tuple(openai_tools_list)
        aggregate: ModelUsage | None = None
        for round_index in range(max_tool_rounds + 1):
            result, message = await self._tool_turn(
                model=model,
                messages=messages,
                tools=openai_tools,
                max_tokens=max_tokens,
            )
            aggregate = self._merge_usage(aggregate, result.usage)
            calls = tuple(message.tool_calls or ())
            if not calls:
                parsed = parse_structured_output(message.content, output_model)
                return ModelResult((), parsed, aggregate)
            if round_index >= max_tool_rounds:
                raise PermanentModelError("tool_loop_round_limit_exceeded")
            messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [call.model_dump(mode="json") for call in calls],
                }
            )
            for call in calls:
                canonical_name = provider_to_canonical.get(call.function.name)
                try:
                    arguments = json.loads(call.function.arguments)
                except json.JSONDecodeError:
                    arguments = None
                if canonical_name is None:
                    output: dict[str, Any] = {
                        "error": {"code": "unknown_provider_tool"}
                    }
                elif not isinstance(arguments, dict):
                    output = {"error": {"code": "tool_input_invalid"}}
                else:
                    output = await executor.execute(canonical_name, arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(output, ensure_ascii=False, sort_keys=True),
                    }
                )
        raise PermanentModelError("tool_loop_round_limit_exceeded")

    async def _tool_turn(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: tuple[dict[str, Any], ...],
        max_tokens: int,
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
                    response = await self._client.chat.completions.create(
                        model=model,
                        messages=cast(Any, messages),
                        tools=cast(Any, tools),
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
