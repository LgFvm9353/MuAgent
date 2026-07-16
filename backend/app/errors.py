from app.harness.model_gateway import ModelGatewayError

_SAFE_MESSAGES = {
    "authentication_failed": "模型服务认证失败，请检查 API Key。",  # noqa: RUF001
    "model_not_found": "模型不存在或当前账户无权访问。",
    "permission_denied": "模型服务拒绝了当前请求。",
    "RateLimitError": "模型服务当前请求过多，请稍后重试。",  # noqa: RUF001
    "APIConnectionError": "无法连接模型服务。",
    "APITimeoutError": "模型服务请求超时。",
    "invalid_structured_output": "模型返回的结构化结果不符合要求。",
    "invalid_provider_request": "模型服务不支持当前请求参数。",
    "invalid_tool_call": "模型返回了无效的工具调用。",
}


def safe_error_summary(error: BaseException) -> tuple[str, str]:
    leaves = _leaves(error)
    selected = next((item for item in leaves if isinstance(item, ModelGatewayError)), leaves[0])
    code = (
        str(selected)
        if isinstance(selected, ModelGatewayError) and str(selected)
        else type(selected).__name__
    )
    return code, _SAFE_MESSAGES.get(
        code,
        "Agent 执行失败，请查看后端日志。",  # noqa: RUF001
    )


def _leaves(error: BaseException) -> list[BaseException]:
    if isinstance(error, BaseExceptionGroup):
        return [leaf for nested in error.exceptions for leaf in _leaves(nested)]
    return [error]
