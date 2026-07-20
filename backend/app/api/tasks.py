import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import database_session
from app.config import get_settings
from app.contracts.task import TaskContract
from app.models import (
    ConversationMessage,
    EvidenceRecordModel,
    ExecutionPlanRecord,
    ExecutionStepRecord,
    Task,
    TaskEvent,
    ToolCall,
    UsageRecord,
    VerificationReportModel,
)
from app.orchestrator.state_machine import TERMINAL_STATES
from app.repositories import TaskNotFoundError, TaskRepository
from app.services.tasks import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])
Session = Annotated[AsyncSession, Depends(database_session)]


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trace_id: UUID
    goal: str
    state: str
    version: int
    cancel_requested: bool
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def extract_goal(cls, value: Any) -> Any:
        if isinstance(value, Task):
            return {
                "id": value.id,
                "trace_id": value.trace_id,
                "goal": str(value.contract.get("goal", "")),
                "state": value.state,
                "version": value.version,
                "cancel_requested": value.cancel_requested,
                "created_at": value.created_at,
                "updated_at": value.updated_at,
            }
        return value


@router.get("", response_model=list[TaskResponse])
async def list_tasks(
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TaskResponse]:
    tasks = await TaskService(session).list(limit=limit, offset=offset)
    return [TaskResponse.model_validate(task) for task in tasks]


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


class TaskResultResponse(BaseModel):
    task: TaskResponse
    plan: dict[str, Any] | None
    plan_version: int | None
    steps: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    verification: dict[str, Any] | None
    evidence: list[dict[str, Any]]
    usage: dict[str, int | float]


@router.get("/{task_id}/result", response_model=TaskResultResponse)
async def task_result(task_id: UUID, session: Session) -> TaskResultResponse:
    try:
        task = await TaskRepository(session).get(task_id)
    except TaskNotFoundError as error:
        raise HTTPException(status_code=404, detail="task not found") from error

    plan = await session.scalar(
        select(ExecutionPlanRecord)
        .where(ExecutionPlanRecord.task_id == task_id)
        .order_by(ExecutionPlanRecord.version.desc())
        .limit(1)
    )
    steps: list[ExecutionStepRecord] = []
    calls: list[ToolCall] = []
    verification: VerificationReportModel | None = None
    if plan is not None:
        steps = list(
            await session.scalars(
                select(ExecutionStepRecord)
                .where(ExecutionStepRecord.plan_id == plan.id)
                .order_by(ExecutionStepRecord.created_at)
            )
        )
        step_ids = [step.id for step in steps]
        if step_ids:
            calls = list(
                await session.scalars(
                    select(ToolCall)
                    .where(ToolCall.step_id.in_(step_ids))
                    .order_by(ToolCall.created_at)
                )
            )
        verification = await session.scalar(
            select(VerificationReportModel)
            .where(
                VerificationReportModel.task_id == task_id,
                VerificationReportModel.plan_id == plan.id,
            )
            .order_by(VerificationReportModel.created_at.desc())
            .limit(1)
        )
    evidence = list(
        await session.scalars(
            select(EvidenceRecordModel)
            .where(EvidenceRecordModel.task_id == task_id)
            .order_by(EvidenceRecordModel.created_at)
        )
    )
    usage_records = list(
        await session.scalars(
            select(UsageRecord)
            .where(UsageRecord.task_id == task_id)
            .order_by(UsageRecord.created_at)
        )
    )
    return TaskResultResponse(
        task=TaskResponse.model_validate(task),
        plan=plan.content if plan is not None else None,
        plan_version=plan.version if plan is not None else None,
        steps=[
            {"id": str(step.id), "status": step.status, "content": step.content}
            for step in steps
        ],
        tool_calls=[
            {
                "id": str(call.id),
                "step_id": str(call.step_id),
                "tool_name": call.tool_name,
                "status": call.status,
                "arguments": {
                    key: value
                    for key, value in call.arguments.items()
                    if key not in {"content", "api_key", "token", "password", "secret"}
                },
                "result": call.result,
                "error_type": call.error_type,
            }
            for call in calls
        ],
        verification=verification.content if verification is not None else None,
        evidence=[
            {
                "id": str(item.id),
                "kind": item.kind,
                "content": item.content,
                "sha256": item.sha256,
                "created_at": item.created_at.isoformat(),
            }
            for item in evidence
        ],
        usage={
            "input_tokens": sum(
                item.input_tokens
                + item.cache_creation_input_tokens
                + item.cache_read_input_tokens
                for item in usage_records
            ),
            "output_tokens": sum(item.output_tokens for item in usage_records),
            "estimated_cost_usd": sum(item.estimated_cost_usd for item in usage_records),
            "latency_ms": sum(item.latency_ms for item in usage_records),
        },
    )


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_type: str
    from_state: str | None
    to_state: str | None
    payload: dict[str, Any]
    created_at: datetime


class ConversationMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: UUID
    agent_id: str
    role: str
    message_type: str
    phase: str
    summary: str
    content: dict[str, Any]
    source_id: str
    created_at: datetime


@router.get(
    "/{task_id}/messages",
    response_model=list[ConversationMessageResponse],
)
async def task_messages(
    task_id: UUID,
    session: Session,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> Sequence[ConversationMessage]:
    try:
        return await TaskRepository(session).messages(task_id, after=after, limit=limit)
    except TaskNotFoundError as error:
        raise HTTPException(status_code=404, detail="task not found") from error


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


def _sse(event: str, data: dict[str, Any], *, event_id: int | None = None) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}")
    return "\n".join(lines) + "\n\n"


def _event_data(event: TaskEvent) -> dict[str, Any]:
    return EventResponse.model_validate(event).model_dump(mode="json")


@router.get("/{task_id}/stream")
async def stream_task_events(
    task_id: UUID,
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
    message_after: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    async with request.app.state.database.session_factory() as session:
        try:
            await TaskRepository(session).get(task_id)
        except TaskNotFoundError as error:
            raise HTTPException(status_code=404, detail="task not found") from error

    settings = get_settings()

    async def generate() -> AsyncIterator[str]:
        cursor = after
        message_cursor = message_after
        since_heartbeat = 0.0
        terminal_values = {state.value for state in TERMINAL_STATES}
        while not await request.is_disconnected():
            async with request.app.state.database.session_factory() as session:
                repository = TaskRepository(session)
                task = await repository.get(task_id)
                events = await repository.timeline_after(task_id, after=cursor)
                messages = await repository.messages(task_id, after=message_cursor)

            stream_items = [
                (event.created_at, 0, event.id, "task_event", _event_data(event))
                for event in events
            ] + [
                (
                    message.created_at,
                    1,
                    message.id,
                    "conversation_message",
                    ConversationMessageResponse.model_validate(message).model_dump(mode="json"),
                )
                for message in messages
            ]
            for _, _, item_id, event_name, data in sorted(stream_items):
                if event_name == "task_event":
                    cursor = item_id
                else:
                    message_cursor = item_id
                yield _sse(event_name, data)

            if task.state in terminal_values and not events and not messages:
                yield _sse("task_complete", {"task_id": str(task_id), "state": task.state})
                return

            await asyncio.sleep(settings.sse_poll_interval_seconds)
            since_heartbeat += settings.sse_poll_interval_seconds
            if since_heartbeat >= settings.sse_heartbeat_seconds:
                yield _sse("heartbeat", {"task_id": str(task_id)})
                since_heartbeat = 0.0

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(task_id: UUID, session: Session, request: Request) -> TaskResponse:
    try:
        task = await TaskService(session).cancel(task_id)
    except TaskNotFoundError as error:
        raise HTTPException(status_code=404, detail="task not found") from error
    await request.app.state.coordinator.cancel(task_id)
    return TaskResponse.model_validate(task)
