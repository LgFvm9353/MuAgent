from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from app.contracts.base import ContractModel
from app.contracts.collaboration import CollaborationMode
from app.contracts.task import TaskContract


class ConversationCreate(ContractModel):
    title: str = Field(default="新对话", min_length=1, max_length=255)


class ConversationResponse(ContractModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    latest_task_id: UUID | None = None
    latest_task_state: str | None = None


class ConversationTurnCreate(ContractModel):
    idempotency_key: UUID
    text: str | None = Field(default=None, min_length=1, max_length=50_000)
    contract: TaskContract | None = None
    skill_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{0,63}$")

    @model_validator(mode="before")
    @classmethod
    def ignore_legacy_collaboration_controls(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        cleaned = dict(value)
        cleaned.pop("collaboration_mode", None)
        cleaned.pop("synthesize", None)
        return cleaned

    @model_validator(mode="after")
    def validate_payload(self) -> "ConversationTurnCreate":
        if (self.text is None) == (self.contract is None):
            raise ValueError("exactly one of text or contract is required")
        return self


class AgentRunResponse(ContractModel):
    id: UUID
    agent_id: str
    model: str
    status: str
    phase: str | None = None
    skill_id: str | None = None


class ConversationTurnResponse(ContractModel):
    turn_id: UUID | None = None
    task_id: UUID | None = None
    conversation_id: UUID
    state: str
    route_source: str | None = None
    collaboration_mode: CollaborationMode | None = None
    synthesize: bool = False
    selected_agents: tuple[str, ...] = ()
    agent_runs: tuple[AgentRunResponse, ...] = ()
