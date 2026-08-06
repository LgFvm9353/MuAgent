from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CollaborationMode(StrEnum):
    SINGLE = "single"
    PARALLEL = "parallel"


class CollaborationPhase(StrEnum):
    ROUTING = "routing"
    SINGLE = "single"
    PARALLEL = "parallel"
    SYNTHESIS = "synthesis"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class AgentRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CollaborationErrorCode(StrEnum):
    AGENT_TIMEOUT = "agent_timeout"
    AGENT_IDLE_STALL = "agent_idle_stall"
    AGENT_CANCELLED = "agent_cancelled"
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_INVALID_OUTPUT = "model_invalid_output"
    TOOL_BUDGET_EXHAUSTED = "tool_budget_exhausted"
    SYNTHESIS_FAILED = "synthesis_failed"


class ActivityTimeouts(BaseModel):
    model_config = ConfigDict(frozen=True)

    first_event_warning_seconds: float = Field(default=10.0, gt=0)
    idle_warning_seconds: float = Field(default=15.0, gt=0)
    idle_stall_seconds: float = Field(default=45.0, gt=0)
    tool_idle_stall_seconds: float = Field(default=90.0, gt=0)
    inactivity_budget_seconds: float = Field(default=120.0, gt=0)
    synthesis_idle_stall_seconds: float = Field(default=30.0, gt=0)
    confirmation_ttl_seconds: float = Field(default=1800.0, gt=0)

    @model_validator(mode="after")
    def validate_timeout_order(self) -> "ActivityTimeouts":
        if self.first_event_warning_seconds > self.idle_warning_seconds:
            raise ValueError("first event warning must not exceed idle warning")
        if self.idle_warning_seconds >= self.idle_stall_seconds:
            raise ValueError("idle warning must be shorter than idle stall")
        if self.idle_stall_seconds > self.tool_idle_stall_seconds:
            raise ValueError("tool idle stall must not be shorter than idle stall")
        return self


class CollaborationPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: CollaborationMode = CollaborationMode.PARALLEL
    synthesize: bool = False
    max_agents: int = Field(default=3, ge=1, le=3)
    max_tool_rounds_per_agent: int = Field(default=6, ge=0, le=20)
    max_tool_calls_per_agent: int = Field(default=10, ge=0, le=50)
    max_tool_calls_per_turn: int = Field(default=20, ge=0, le=100)

    @model_validator(mode="after")
    def validate_mode_boundaries(self) -> "CollaborationPolicy":
        if self.mode is CollaborationMode.SINGLE and self.max_agents != 1:
            raise ValueError("single mode must use exactly one agent")
        if self.max_tool_calls_per_agent > self.max_tool_calls_per_turn:
            raise ValueError("per-agent tool budget must not exceed turn tool budget")
        return self
