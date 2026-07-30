import os
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.mcp.contracts import McpConfig, McpServerConfig, McpTransport


class McpConfigError(ValueError):
    pass


def load_mcp_config(path: Path, *, allow_local_http: bool = False) -> McpConfig:
    if not path.exists():
        return McpConfig()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        config = McpConfig.model_validate(raw or {})
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError) as error:
        raise McpConfigError("invalid MCP configuration") from error
    for server in config.servers:
        _validate_server(server, allow_local_http=allow_local_http)
    return config


def _validate_server(server: McpServerConfig, *, allow_local_http: bool) -> None:
    if server.transport is McpTransport.STREAMABLE_HTTP and server.url is not None:
        url = server.url
        is_local = url.host in {"localhost", "127.0.0.1", "::1"}
        if url.scheme != "https" and not (allow_local_http and is_local):
            raise McpConfigError(f"MCP server {server.id} must use HTTPS")
    missing = [variable for variable in server.headers_from_env.values() if not os.getenv(variable)]
    if missing:
        raise McpConfigError(f"MCP server {server.id} is missing required environment variables")


def resolved_headers(server: McpServerConfig) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name, variable in server.headers_from_env.items():
        value = os.getenv(variable)
        if value is None:
            raise McpConfigError(f"missing MCP credential for server {server.id}")
        headers[name] = value
    return headers
