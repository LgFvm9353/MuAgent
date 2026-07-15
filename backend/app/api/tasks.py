from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import database_session
from app.contracts.task import TaskContract
from app.repositories import TaskNotFoundError, TaskRepository
from app.services.tasks import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])
Session = Annotated[AsyncSession, Depends(database_session)]


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    trace_id: UUID
    state: str
    version: int
    cancel_requested: bool


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(contract: TaskContract, session: Session, request: Request) -> TaskResponse:
    task = await TaskService(session).create(contract)
    await request.app.state.coordinator.schedule(task.id)
    return TaskResponse.model_validate(task)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: UUID, session: Session) -> TaskResponse:
    try:
        task = await TaskService(session).get(task_id)
    except TaskNotFoundError as error:
        raise HTTPException(status_code=404, detail="task not found") from error
    return TaskResponse.model_validate(task)


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_type: str
    from_state: str | None
    to_state: str | None
    payload: dict[str, Any]
    created_at: datetime


class AuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class UsageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    request_id: str | None
    model: str
    stop_reason: str | None
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    latency_ms: int
    retry_count: int
    estimated_cost_usd: float
    created_at: datetime


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: str
    content: dict[str, Any]
    sha256: str | None
    created_at: datetime


async def _repository_result(
    task_id: UUID,
    operation: Callable[[UUID], Awaitable[Sequence[Any]]],
) -> Sequence[Any]:
    try:
        return await operation(task_id)
    except TaskNotFoundError as error:
        raise HTTPException(status_code=404, detail="task not found") from error


@router.get("/{task_id}/events", response_model=list[EventResponse])
async def task_events(task_id: UUID, session: Session) -> Sequence[Any]:
    return await _repository_result(task_id, TaskRepository(session).timeline)


@router.get("/{task_id}/audit", response_model=list[AuditResponse])
async def task_audit(task_id: UUID, session: Session) -> Sequence[Any]:
    return await _repository_result(task_id, TaskRepository(session).audit)


@router.get("/{task_id}/usage", response_model=list[UsageResponse])
async def task_usage(task_id: UUID, session: Session) -> Sequence[Any]:
    return await _repository_result(task_id, TaskRepository(session).usage)


@router.get("/{task_id}/evidence", response_model=list[EvidenceResponse])
async def task_evidence(task_id: UUID, session: Session) -> Sequence[Any]:
    return await _repository_result(task_id, TaskRepository(session).evidence)


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(task_id: UUID, session: Session, request: Request) -> TaskResponse:
    try:
        task = await TaskService(session).cancel(task_id)
    except TaskNotFoundError as error:
        raise HTTPException(status_code=404, detail="task not found") from error
    await request.app.state.coordinator.cancel(task_id)
    return TaskResponse.model_validate(task)
