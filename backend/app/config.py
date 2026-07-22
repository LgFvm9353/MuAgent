from functools import lru_cache
from pathlib import Path
from typing import Literal, cast

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AgentId = Literal["architect", "reviewer", "designer"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "mysql+asyncmy://root:root@localhost:3306/agent?charset=utf8mb4"
    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-4-8"
    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api-slb.krill-ai.com/codex/v1"
    openai_model: str = "gpt-5.6-sol"
    architect_model: str = "gpt-5.6-sol"
    reviewer_model: str = "gpt-5.4"
    designer_model: str = "gpt-5.5"
    verifier_model: str | None = None
    workspace_root: Path = Path("data/workspaces")
    artifacts_root: Path = Path("data/artifacts")
    model_concurrency: int = Field(default=4, ge=1, le=32)
    model_timeout_seconds: float = Field(default=600.0, gt=0)
    tool_timeout_seconds: float = Field(default=120.0, gt=0)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    sse_poll_interval_seconds: float = Field(default=1.0, gt=0)
    sse_heartbeat_seconds: float = Field(default=15.0, gt=0)
    log_level: str = "INFO"

    @property
    def model_name(self) -> str:
        return self.openai_model if self.llm_provider == "openai" else self.anthropic_model

    def agent_model(self, agent_id: AgentId) -> str:
        field_by_agent: dict[AgentId, str] = {
            "architect": "architect_model",
            "reviewer": "reviewer_model",
            "designer": "designer_model",
        }
        try:
            field_name = field_by_agent[agent_id]
        except KeyError as error:
            raise ValueError(f"unknown agent ID: {agent_id}") from error
        configured = cast(str | None, getattr(self, field_name))
        if configured is not None and configured.strip():
            return configured.strip()
        return self.model_name

    @model_validator(mode="after")
    def validate_provider(self) -> "Settings":
        key = self.openai_api_key if self.llm_provider == "openai" else self.anthropic_api_key
        if key is None or not key.get_secret_value().strip():
            raise ValueError(f"{self.llm_provider} API key is required")
        if self.llm_provider == "openai" and not self.openai_base_url.startswith("https://"):
            raise ValueError("OPENAI_BASE_URL must use HTTPS")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
