import asyncio
import json
from time import monotonic
from typing import Any, TypeVar

import openai
from pydantic import BaseModel, ValidationError

from app.harness.model_gateway import (
    ModelGatewayError,
    ModelResult,
    ModelUsage,
    PermanentModelError,
    RetryableModelError,
)

OutputT = TypeVar("OutputT", bound=BaseModel)


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
        max_tokens: int = 16_000,
        effort: str = "high",
    ) -> ModelResult:
        del effort
        schema = json.dumps(
            output_model.model_json_schema(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        structured_system = (
            f"{system}\n\n"
            "你必须只输出一个符合以下 JSON Schema 的 JSON 对象。"
            "不要输出 Markdown 代码块、解释、注释、前缀或后缀。"
            "输出必须能被标准 JSON 解析器直接解析。\n"
            f"JSON Schema:\n{schema}"
        )
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
        try:
            parsed = output_model.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError) as error:
            raise PermanentModelError("invalid_structured_output") from error

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
            return PermanentModelError("invalid_provider_request")
        return PermanentModelError(type(error).__name__)
