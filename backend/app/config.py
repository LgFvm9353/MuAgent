from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAG_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/rag"
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-4-8"
    workspace_root: Path = Path("data/workspaces")
    artifacts_root: Path = Path("data/artifacts")
    model_concurrency: int = Field(default=4, ge=1, le=32)
    model_timeout_seconds: float = Field(default=600.0, gt=0)
    tool_timeout_seconds: float = Field(default=120.0, gt=0)
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
