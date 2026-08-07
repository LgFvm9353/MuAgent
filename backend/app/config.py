from functools import lru_cache
from pathlib import Path
from typing import Literal, get_args

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config_defaults import (
    DEFAULT_ARTIFACTS_ROOT,
    DEFAULT_COLLABORATION_CONFIRMATION_TTL_SECONDS,
    DEFAULT_COLLABORATION_DEFAULT_MODE,
    DEFAULT_COLLABORATION_DEFAULT_SYNTHESIZE,
    DEFAULT_COLLABORATION_FIRST_EVENT_WARNING_SECONDS,
    DEFAULT_COLLABORATION_IDLE_STALL_SECONDS,
    DEFAULT_COLLABORATION_IDLE_WARNING_SECONDS,
    DEFAULT_COLLABORATION_INACTIVITY_BUDGET_SECONDS,
    DEFAULT_COLLABORATION_MAX_AGENTS,
    DEFAULT_COLLABORATION_MAX_TOOL_CALLS_PER_AGENT,
    DEFAULT_COLLABORATION_MAX_TOOL_CALLS_PER_TURN,
    DEFAULT_COLLABORATION_MAX_TOOL_ROUNDS_PER_AGENT,
    DEFAULT_COLLABORATION_SYNTHESIS_IDLE_STALL_SECONDS,
    DEFAULT_COLLABORATION_TOOL_IDLE_STALL_SECONDS,
    DEFAULT_CONTEXT_COMPRESSION_TARGET,
    DEFAULT_CONTEXT_COMPRESSION_THRESHOLD,
    DEFAULT_CONTEXT_MODEL_MAX_OUTPUT_TOKENS,
    DEFAULT_CONTEXT_MODEL_WINDOWS,
    DEFAULT_CONTEXT_RECENT_MESSAGES,
    DEFAULT_CONTEXT_SAFETY_MARGIN_RATIO,
    DEFAULT_CONTEXT_UNKNOWN_MODEL_MAX_OUTPUT_TOKENS,
    DEFAULT_CONTEXT_UNKNOWN_MODEL_WINDOW,
    DEFAULT_CORS_ORIGINS,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MCP_CLOSE_TIMEOUT_SECONDS,
    DEFAULT_MCP_CONFIG_PATH,
    DEFAULT_MCP_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_MCP_READ_TOOL_TIMEOUT_SECONDS,
    DEFAULT_MCP_TOOL_TIMEOUT_SECONDS,
    DEFAULT_MEMORY_AUTO_CONSOLIDATION_ENABLED,
    DEFAULT_MEMORY_CONSOLIDATION_MAX_ATTEMPTS,
    DEFAULT_MEMORY_DEFAULT_OWNER_ID,
    DEFAULT_MEMORY_ENABLED,
    DEFAULT_MEMORY_ENVIRONMENT_ENABLED,
    DEFAULT_MEMORY_ENVIRONMENT_MAX_FILE_BYTES,
    DEFAULT_MEMORY_EPISODIC_ENABLED,
    DEFAULT_MEMORY_HARD_ENABLED,
    DEFAULT_MEMORY_MAX_CONTEXT_ITEMS,
    DEFAULT_MEMORY_MAX_CONTEXT_TOKENS,
    DEFAULT_MEMORY_MIN_RETRIEVAL_SCORE,
    DEFAULT_MEMORY_RETENTION_DAYS,
    DEFAULT_MENTION_EXECUTION_TOOLS,
    DEFAULT_MODEL_CONCURRENCY,
    DEFAULT_MODEL_TIMEOUT_SECONDS,
    DEFAULT_SKILLS_ROOT,
    DEFAULT_SSE_HEARTBEAT_SECONDS,
    DEFAULT_SSE_POLL_INTERVAL_SECONDS,
    DEFAULT_TOOL_TIMEOUT_SECONDS,
    DEFAULT_WORKSPACE_ROOT,
)
from app.contracts.collaboration import ActivityTimeouts, CollaborationMode, CollaborationPolicy

AgentId = Literal[
    "scout",
    "researcher",
    "planner",
    "worker",
    "reviewer",
    "context-builder",
    "oracle",
    "delegate",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "mysql+asyncmy://root:root@localhost:3306/agent?charset=utf8mb4"
    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str | None = None
    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None
    openai_model: str | None = None
    router_model: str | None = None
    workspace_root: Path = Path(DEFAULT_WORKSPACE_ROOT)
    artifacts_root: Path = Path(DEFAULT_ARTIFACTS_ROOT)
    model_concurrency: int = Field(default=DEFAULT_MODEL_CONCURRENCY, ge=1, le=32)
    model_timeout_seconds: float = Field(default=DEFAULT_MODEL_TIMEOUT_SECONDS, gt=0)
    context_compression_model: str | None = None
    context_compression_model_context_window: int | None = Field(default=None, ge=16_384)
    context_compression_model_max_output_tokens: int | None = Field(default=None, ge=1_024)
    context_compression_threshold: float = Field(
        default=DEFAULT_CONTEXT_COMPRESSION_THRESHOLD, gt=0, le=1
    )
    context_compression_target: float = Field(
        default=DEFAULT_CONTEXT_COMPRESSION_TARGET, gt=0, le=1
    )
    context_safety_margin_ratio: float = Field(
        default=DEFAULT_CONTEXT_SAFETY_MARGIN_RATIO, ge=0, le=0.20
    )
    context_unknown_model_window: int = Field(
        default=DEFAULT_CONTEXT_UNKNOWN_MODEL_WINDOW, ge=16_384
    )
    context_unknown_model_max_output_tokens: int = Field(
        default=DEFAULT_CONTEXT_UNKNOWN_MODEL_MAX_OUTPUT_TOKENS, ge=1_024
    )
    context_model_windows: str = DEFAULT_CONTEXT_MODEL_WINDOWS
    context_model_max_output_tokens: str = DEFAULT_CONTEXT_MODEL_MAX_OUTPUT_TOKENS
    context_recent_messages: int = Field(default=DEFAULT_CONTEXT_RECENT_MESSAGES, ge=2, le=100)
    memory_enabled: bool = DEFAULT_MEMORY_ENABLED
    memory_hard_enabled: bool = DEFAULT_MEMORY_HARD_ENABLED
    memory_environment_enabled: bool = DEFAULT_MEMORY_ENVIRONMENT_ENABLED
    memory_episodic_enabled: bool = DEFAULT_MEMORY_EPISODIC_ENABLED
    memory_auto_consolidation_enabled: bool = DEFAULT_MEMORY_AUTO_CONSOLIDATION_ENABLED
    memory_default_owner_id: str = Field(
        default=DEFAULT_MEMORY_DEFAULT_OWNER_ID, min_length=1, max_length=100
    )
    memory_max_context_items: int = Field(default=DEFAULT_MEMORY_MAX_CONTEXT_ITEMS, ge=1, le=20)
    memory_max_context_tokens: int = Field(
        default=DEFAULT_MEMORY_MAX_CONTEXT_TOKENS, ge=512, le=64_000
    )
    memory_min_retrieval_score: float = Field(
        default=DEFAULT_MEMORY_MIN_RETRIEVAL_SCORE, ge=0, le=1
    )
    memory_consolidation_max_attempts: int = Field(
        default=DEFAULT_MEMORY_CONSOLIDATION_MAX_ATTEMPTS, ge=1, le=10
    )
    memory_retention_days: int = Field(default=DEFAULT_MEMORY_RETENTION_DAYS, ge=1, le=3_650)
    memory_environment_max_file_bytes: int = Field(
        default=DEFAULT_MEMORY_ENVIRONMENT_MAX_FILE_BYTES, ge=1_024, le=2_097_152
    )
    tool_timeout_seconds: float = Field(default=DEFAULT_TOOL_TIMEOUT_SECONDS, gt=0)
    mention_execution_tools: str = DEFAULT_MENTION_EXECUTION_TOOLS
    collaboration_default_mode: Literal["single", "parallel"] = DEFAULT_COLLABORATION_DEFAULT_MODE
    collaboration_default_synthesize: bool = DEFAULT_COLLABORATION_DEFAULT_SYNTHESIZE
    collaboration_max_agents: int = Field(default=DEFAULT_COLLABORATION_MAX_AGENTS, ge=2, le=3)
    collaboration_max_tool_rounds_per_agent: int = Field(
        default=DEFAULT_COLLABORATION_MAX_TOOL_ROUNDS_PER_AGENT, ge=0, le=20
    )
    collaboration_max_tool_calls_per_agent: int = Field(
        default=DEFAULT_COLLABORATION_MAX_TOOL_CALLS_PER_AGENT, ge=0, le=50
    )
    collaboration_max_tool_calls_per_turn: int = Field(
        default=DEFAULT_COLLABORATION_MAX_TOOL_CALLS_PER_TURN, ge=0, le=100
    )
    collaboration_first_event_warning_seconds: float = Field(
        default=DEFAULT_COLLABORATION_FIRST_EVENT_WARNING_SECONDS, gt=0
    )
    collaboration_idle_warning_seconds: float = Field(
        default=DEFAULT_COLLABORATION_IDLE_WARNING_SECONDS, gt=0
    )
    collaboration_idle_stall_seconds: float = Field(
        default=DEFAULT_COLLABORATION_IDLE_STALL_SECONDS, gt=0
    )
    collaboration_tool_idle_stall_seconds: float = Field(
        default=DEFAULT_COLLABORATION_TOOL_IDLE_STALL_SECONDS, gt=0
    )
    collaboration_inactivity_budget_seconds: float = Field(
        default=DEFAULT_COLLABORATION_INACTIVITY_BUDGET_SECONDS, gt=0
    )
    collaboration_synthesis_idle_stall_seconds: float = Field(
        default=DEFAULT_COLLABORATION_SYNTHESIS_IDLE_STALL_SECONDS, gt=0
    )
    collaboration_confirmation_ttl_seconds: float = Field(
        default=DEFAULT_COLLABORATION_CONFIRMATION_TTL_SECONDS, gt=0
    )
    skills_root: Path = Path(DEFAULT_SKILLS_ROOT)
    mcp_config_path: Path = Path(DEFAULT_MCP_CONFIG_PATH)
    mcp_connect_timeout_seconds: float = Field(
        default=DEFAULT_MCP_CONNECT_TIMEOUT_SECONDS, gt=0, le=300.0
    )
    mcp_read_tool_timeout_seconds: float = Field(
        default=DEFAULT_MCP_READ_TOOL_TIMEOUT_SECONDS, gt=0, le=300.0
    )
    mcp_tool_timeout_seconds: float = Field(
        default=DEFAULT_MCP_TOOL_TIMEOUT_SECONDS, gt=0, le=300.0
    )
    mcp_close_timeout_seconds: float = Field(
        default=DEFAULT_MCP_CLOSE_TIMEOUT_SECONDS, gt=0, le=5.0
    )
    cors_origins: str = DEFAULT_CORS_ORIGINS
    sse_poll_interval_seconds: float = Field(default=DEFAULT_SSE_POLL_INTERVAL_SECONDS, gt=0)
    sse_heartbeat_seconds: float = Field(default=DEFAULT_SSE_HEARTBEAT_SECONDS, gt=0)
    log_level: str = DEFAULT_LOG_LEVEL

    @property
    def gateway_api_key(self) -> SecretStr:
        key = self.llm_api_key or self.openai_api_key
        if key is None or not key.get_secret_value().strip():
            raise ValueError("LLM_API_KEY or OPENAI_API_KEY is required")
        return key

    @property
    def gateway_base_url(self) -> str:
        configured = self.llm_base_url or self.openai_base_url
        if not configured:
            raise ValueError("OPENAI_BASE_URL or LLM_BASE_URL is required")
        return configured.rstrip("/")

    @property
    def router_model_name(self) -> str:
        configured = self.router_model
        return configured.strip() if configured and configured.strip() else self.model_name

    @property
    def model_name(self) -> str:
        if self.llm_provider == "openai":
            if not self.openai_model or not self.openai_model.strip():
                raise ValueError("OPENAI_MODEL is required")
            return self.openai_model.strip()
        if not self.anthropic_model or not self.anthropic_model.strip():
            raise ValueError("ANTHROPIC_MODEL is required")
        return self.anthropic_model.strip()

    def agent_model(self, agent_id: AgentId) -> str:
        # All capability agents intentionally share the provider/model selected
        # through OPENAI_BASE_URL and OPENAI_MODEL (or the Anthropic provider).
        if agent_id not in get_args(AgentId):
            raise ValueError(f"unknown agent ID: {agent_id}")
        return self.model_name

    @property
    def collaboration_timeouts(self) -> ActivityTimeouts:
        return ActivityTimeouts(
            first_event_warning_seconds=self.collaboration_first_event_warning_seconds,
            idle_warning_seconds=self.collaboration_idle_warning_seconds,
            idle_stall_seconds=self.collaboration_idle_stall_seconds,
            tool_idle_stall_seconds=self.collaboration_tool_idle_stall_seconds,
            inactivity_budget_seconds=self.collaboration_inactivity_budget_seconds,
            synthesis_idle_stall_seconds=self.collaboration_synthesis_idle_stall_seconds,
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
            max_agents=self.collaboration_max_agents
            if selected_mode is CollaborationMode.PARALLEL
            else 1,
            max_tool_rounds_per_agent=self.collaboration_max_tool_rounds_per_agent,
            max_tool_calls_per_agent=self.collaboration_max_tool_calls_per_agent,
            max_tool_calls_per_turn=self.collaboration_max_tool_calls_per_turn,
        )

    @model_validator(mode="after")
    def validate_provider(self) -> "Settings":
        _ = self.collaboration_timeouts
        _ = self.collaboration_policy()
        if self.context_compression_target >= self.context_compression_threshold:
            raise ValueError("CONTEXT_COMPRESSION_TARGET must be below threshold")
        if self.llm_api_key is not None:
            if not self.llm_api_key.get_secret_value().strip():
                raise ValueError("LLM_API_KEY must not be empty")
            if not self.gateway_base_url.startswith("https://"):
                raise ValueError("LLM_BASE_URL must use HTTPS")
            return self

        key = self.openai_api_key if self.llm_provider == "openai" else self.anthropic_api_key
        if key is None or not key.get_secret_value().strip():
            raise ValueError(f"{self.llm_provider} API key is required")
        if self.llm_provider == "openai" and (
            not self.openai_base_url or not self.openai_base_url.startswith("https://")
        ):
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
