from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.config_defaults import PROVIDER_REQUEST_TIMEOUT_SECONDS
from app.contracts.task import RiskLevel


class McpTransport(StrEnum):
    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"


class McpToolPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    risk: RiskLevel
    idempotent: bool = False
    timeout_seconds: float | None = Field(
        default=None, gt=0, le=PROVIDER_REQUEST_TIMEOUT_SECONDS
    )


class McpServerConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    enabled: bool = True
    transport: McpTransport
    command: str | None = None
    args: tuple[str, ...] = ()
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    url: HttpUrl | None = None
    headers_from_env: dict[str, str] = Field(default_factory=dict)
    tools: dict[str, McpToolPolicy] = Field(min_length=1)
    connect_timeout_seconds: float = Field(
        default=300, gt=0, le=PROVIDER_REQUEST_TIMEOUT_SECONDS
    )

    @model_validator(mode="after")
    def validate_transport(self) -> "McpServerConfig":
        if self.transport is McpTransport.STDIO:
            if not self.command or self.url is not None:
                raise ValueError("stdio server requires command and forbids url")
        elif self.url is None or self.command is not None or self.args:
            raise ValueError("streamable HTTP server requires url and forbids command/args")
        return self


class McpConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    servers: tuple[McpServerConfig, ...] = ()

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "McpConfig":
        ids = [server.id for server in self.servers]
        if len(ids) != len(set(ids)):
            raise ValueError("MCP server IDs must be unique")
        return self
