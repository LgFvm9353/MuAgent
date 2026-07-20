from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.contracts.base import ContractModel
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
    contract: TaskContract


class ConversationTurnResponse(ContractModel):
    task_id: UUID
    conversation_id: UUID
    state: str
