from functools import lru_cache
from pathlib import Path
from typing import Literal, cast

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.contracts.collaboration import ActivityTimeouts, CollaborationMode, CollaborationPolicy

AgentId = Literal["architect", "reviewer", "designer"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "mysql+asyncmy://root:root@localhost:3306/agent?charset=utf8mb4"
    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-4-8"
    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api-slb.krill-ai.com/codex/v1"
    openai_model: str = "gpt-5.6-sol"
    architect_model: str = "gpt-5.6-sol"
    reviewer_model: str = "gpt-5.4"
    designer_model: str = "gpt-5.5"
    router_model: str | None = None
    verifier_model: str | None = None
    max_auto_routed_agents: int = Field(default=2, ge=1, le=3)
    workspace_root: Path = Path("data/workspaces")
    artifacts_root: Path = Path("data/artifacts")
    model_concurrency: int = Field(default=4, ge=1, le=32)
    model_timeout_seconds: float = Field(default=600.0, gt=0)
    tool_timeout_seconds: float = Field(default=120.0, gt=0)
    mention_execution_tools: str = (
        "list_workspace_files,read_workspace_file,create_workspace_file,"
        "modify_workspace_file,run_allowlisted_check"
    )
    max_handoff_depth: int = Field(default=10, ge=1, le=50)
    max_thread_invocations: int = Field(default=100, ge=1, le=1000)
    max_ping_pong_streak: int = Field(default=4, ge=2, le=20)
    collaboration_default_mode: Literal["parallel", "serial"] = "parallel"
    collaboration_default_synthesize: bool = False
    collaboration_max_agents: int = Field(default=3, ge=1, le=3)
    collaboration_max_handoff_depth: int = Field(default=1, ge=0, le=1)
    collaboration_max_tool_rounds_per_agent: int = Field(default=6, ge=0, le=20)
    collaboration_max_tool_calls_per_agent: int = Field(default=10, ge=0, le=50)
    collaboration_max_tool_calls_per_turn: int = Field(default=20, ge=0, le=100)
    collaboration_first_event_warning_seconds: float = Field(default=10.0, gt=0)
    collaboration_idle_warning_seconds: float = Field(default=15.0, gt=0)
    collaboration_idle_stall_seconds: float = Field(default=45.0, gt=0)
    collaboration_tool_idle_stall_seconds: float = Field(default=90.0, gt=0)
    collaboration_inactivity_budget_seconds: float = Field(default=120.0, gt=0)
    collaboration_agent_hard_timeout_seconds: float = Field(default=300.0, gt=0)
    collaboration_handoff_hard_timeout_seconds: float = Field(default=180.0, gt=0)
    collaboration_synthesis_idle_stall_seconds: float = Field(default=30.0, gt=0)
    collaboration_synthesis_hard_timeout_seconds: float = Field(default=120.0, gt=0)
    collaboration_turn_hard_timeout_seconds: float = Field(default=480.0, gt=0)
    collaboration_confirmation_ttl_seconds: float = Field(default=1800.0, gt=0)
    skills_root: Path = Path("skills")
    mcp_config_path: Path = Path("config/mcp_servers.yaml")
    mcp_connect_timeout_seconds: float = Field(default=15.0, gt=0, le=300.0)
    mcp_read_tool_timeout_seconds: float = Field(default=30.0, gt=0, le=300.0)
    mcp_tool_timeout_seconds: float = Field(default=60.0, gt=0, le=300.0)
    mcp_close_timeout_seconds: float = Field(default=0.5, gt=0, le=5.0)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    sse_poll_interval_seconds: float = Field(default=1.0, gt=0)
    sse_heartbeat_seconds: float = Field(default=15.0, gt=0)
    log_level: str = "INFO"

    @property
    def gateway_api_key(self) -> SecretStr:
        key = self.llm_api_key or self.openai_api_key
        if key is None or not key.get_secret_value().strip():
            raise ValueError("LLM_API_KEY or OPENAI_API_KEY is required")
        return key

    @property
    def gateway_base_url(self) -> str:
        return (self.llm_base_url or self.openai_base_url).rstrip("/")

    @property
    def router_model_name(self) -> str:
        configured = self.router_model
        return configured.strip() if configured and configured.strip() else self.model_name

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

    @property
    def collaboration_timeouts(self) -> ActivityTimeouts:
        return ActivityTimeouts(
            first_event_warning_seconds=self.collaboration_first_event_warning_seconds,
            idle_warning_seconds=self.collaboration_idle_warning_seconds,
            idle_stall_seconds=self.collaboration_idle_stall_seconds,
            tool_idle_stall_seconds=self.collaboration_tool_idle_stall_seconds,
            inactivity_budget_seconds=self.collaboration_inactivity_budget_seconds,
            agent_hard_timeout_seconds=self.collaboration_agent_hard_timeout_seconds,
            handoff_hard_timeout_seconds=self.collaboration_handoff_hard_timeout_seconds,
            synthesis_idle_stall_seconds=self.collaboration_synthesis_idle_stall_seconds,
            synthesis_hard_timeout_seconds=self.collaboration_synthesis_hard_timeout_seconds,
            turn_hard_timeout_seconds=self.collaboration_turn_hard_timeout_seconds,
            confirmation_ttl_seconds=self.collaboration_confirmation_ttl_seconds,
        )

    def collaboration_policy(
        self,
        mode: CollaborationMode | None = None,
        *,
        synthesize: bool | None = None,
    ) -> CollaborationPolicy:
        selected_mode = mode or CollaborationMode(self.collaboration_default_mode)
        return CollaborationPolicy(
            mode=selected_mode,
            synthesize=self.collaboration_default_synthesize if synthesize is None else synthesize,
            max_agents=(
                self.collaboration_max_agents
                if selected_mode is CollaborationMode.PARALLEL
                else 1
            ),
            max_handoff_depth=(
                0
                if selected_mode is CollaborationMode.PARALLEL
                else self.collaboration_max_handoff_depth
            ),
            max_tool_rounds_per_agent=self.collaboration_max_tool_rounds_per_agent,
            max_tool_calls_per_agent=self.collaboration_max_tool_calls_per_agent,
            max_tool_calls_per_turn=self.collaboration_max_tool_calls_per_turn,
        )

    @model_validator(mode="after")
    def validate_provider(self) -> "Settings":
        _ = self.collaboration_timeouts
        _ = self.collaboration_policy()
        if self.llm_api_key is not None:
            if not self.llm_api_key.get_secret_value().strip():
                raise ValueError("LLM_API_KEY must not be empty")
            if not self.gateway_base_url.startswith("https://"):
                raise ValueError("LLM_BASE_URL must use HTTPS")
            return self

        key = self.openai_api_key if self.llm_provider == "openai" else self.anthropic_api_key
        if key is None or not key.get_secret_value().strip():
            raise ValueError(f"{self.llm_provider} API key is required")
        if self.llm_provider == "openai" and not self.openai_base_url.startswith("https://"):
            raise ValueError("OPENAI_BASE_URL must use HTTPS")
        return self

    @property
    def mention_execution_tool_set(self) -> frozenset[str]:
        return frozenset(
            name.strip() for name in self.mention_execution_tools.split(",") if name.strip()
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
