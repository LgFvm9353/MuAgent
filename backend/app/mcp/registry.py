from collections.abc import Callable
from typing import Any

from jsonschema import Draft202012Validator, SchemaError, ValidationError
from pydantic import BaseModel

from app.mcp.contracts import McpConfig
from app.mcp.manager import McpManager
from app.mcp.tool_backend import McpToolBackend, McpToolInput, McpToolOutput
from app.tools.contracts import ToolSource
from app.tools.registry import ToolDefinition, ToolRegistry


class McpToolRegistrationError(ValueError):
    pass


def _validator(schema: dict[str, Any]) -> Draft202012Validator:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise McpToolRegistrationError("MCP tool published an invalid input schema") from error
    return Draft202012Validator(schema)


def _validate_arguments(
    request: BaseModel,
    validator: Draft202012Validator,
) -> None:
    try:
        validator.validate(request.model_dump(mode="json"))
    except ValidationError as error:
        raise ValueError("arguments do not match the MCP tool schema") from error


def _input_validator(
    validator: Draft202012Validator,
) -> Callable[[McpToolInput], None]:
    def validate(request: McpToolInput) -> None:
        _validate_arguments(request, validator)

    return validate


async def register_mcp_tools(
    registry: ToolRegistry,
    manager: McpManager,
    config: McpConfig,
    *,
    max_output_bytes: int = 1_000_000,
) -> frozenset[str]:
    registered: set[str] = set()
    for server in config.servers:
        if not server.enabled:
            continue
        discovered = {tool.name: tool for tool in await manager.discover(server.id)}
        for tool_name, policy in sorted(server.tools.items()):
            remote = discovered.get(tool_name)
            if remote is None:
                continue
            public_name = f"mcp.{server.id}.{tool_name}"
            validator = _validator(remote.input_schema)
            backend = McpToolBackend(manager, server.id, tool_name)
            registry.register(
                ToolDefinition[McpToolInput, McpToolOutput](
                    name=public_name,
                    description=remote.description,
                    input_model=McpToolInput,
                    output_model=McpToolOutput,
                    risk=policy.risk,
                    timeout_seconds=policy.timeout_seconds or 60.0,
                    idempotent=policy.idempotent,
                    max_output_bytes=max_output_bytes,
                    handler=backend,
                    validate_input=_input_validator(validator),
                    input_json_schema=remote.input_schema,
                    source=ToolSource.MCP,
                    canonical_id=public_name,
                )
            )
            registered.add(public_name)
    return frozenset(registered)
