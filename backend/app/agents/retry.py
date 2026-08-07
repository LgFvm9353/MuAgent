from app.harness.model_gateway import ModelGatewayError
from app.harness.structured_tools import StructuredOutputError

_RETRYABLE_RESULT_CODES = frozenset(
    {
        "empty_model_response",
        "empty_structured_output",
        "invalid_structured_output",
        "agent returned no chat reply",
        "model request completed without a response",
    }
)


def is_retryable_agent_error(error: BaseException) -> bool:
    """Return whether rerunning the whole agent attempt is safe and useful."""
    if isinstance(error, BaseExceptionGroup):
        return any(is_retryable_agent_error(item) for item in error.exceptions)
    if isinstance(error, StructuredOutputError):
        return str(error) in _RETRYABLE_RESULT_CODES
    if isinstance(error, ModelGatewayError):
        return error.retryable or str(error) in _RETRYABLE_RESULT_CODES
    return str(error) in _RETRYABLE_RESULT_CODES


def retry_delay_seconds(completed_attempt: int) -> float:
    """Bounded exponential delay after a failed 1-based attempt."""
    return float(min(2 ** max(0, completed_attempt - 1), 8))
