import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import database_session
from app.contracts.conversation import (
    ConversationCreate,
    ConversationResponse,
    ConversationTurnCreate,
    ConversationTurnResponse,
)
from app.models import Conversation, ConversationMessage, Task
from app.orchestrator.state_machine import TERMINAL_STATES
from app.repositories import TaskRepository

router = APIRouter(prefix="/conversations", tags=["conversations"])
Session = Annotated[AsyncSession, Depends(database_session)]
_TERMINAL_VALUES = {state.value for state in TERMINAL_STATES}


def _response(conversation: Conversation, latest: Task | None = None) -> ConversationResponse:
    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        latest_task_id=latest.id if latest else None,
        latest_task_state=latest.state if latest else None,
    )


async def _latest_task(session: AsyncSession, conversation_id: UUID) -> Task | None:
    return await session.scalar(
        select(Task)
        .where(Task.conversation_id == conversation_id)
        .order_by(Task.created_at.desc())
        .limit(1)
    )


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(payload: ConversationCreate, session: Session) -> ConversationResponse:
    conversation = Conversation(title=payload.title.strip())
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return _response(conversation)


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ConversationResponse]:
    conversations = list(
        await session.scalars(
            select(Conversation)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return [
        _response(conversation, await _latest_task(session, conversation.id))
        for conversation in conversations
    ]


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(conversation_id: UUID, session: Session) -> ConversationResponse:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return _response(conversation, await _latest_task(session, conversation_id))


@router.post(
    "/{conversation_id}/messages",
    response_model=ConversationTurnResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_turn(
    conversation_id: UUID,
    payload: ConversationTurnCreate,
    session: Session,
    request: Request,
) -> ConversationTurnResponse:
    conversation = await session.scalar(
        select(Conversation).where(Conversation.id == conversation_id).with_for_update()
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")

    source_id = f"user:{payload.idempotency_key}"
    existing = await session.scalar(
        select(ConversationMessage)
        .join(Task, Task.id == ConversationMessage.task_id)
        .where(
            Task.conversation_id == conversation_id,
            ConversationMessage.source_id == source_id,
        )
    )
    if existing is not None:
        task = await session.get(Task, existing.task_id)
        if task is None:
            raise HTTPException(status_code=409, detail="idempotent task no longer exists")
        return ConversationTurnResponse(
            task_id=task.id,
            conversation_id=conversation_id,
            state=task.state,
        )

    latest = await _latest_task(session, conversation_id)
    if latest is not None and latest.state not in _TERMINAL_VALUES:
        raise HTTPException(status_code=409, detail="conversation_busy")

    contract = payload.contract
    task = Task(
        id=contract.task_id,
        conversation_id=conversation_id,
        trace_id=payload.idempotency_key,
        contract=contract.model_dump(mode="json"),
    )
    await TaskRepository(session).add(task)
    # Persist the parent task before inserting its first message. The models do not
    # expose an ORM relationship, so SQLAlchemy cannot infer object-level flush order.
    await session.flush()
    session.add(
        ConversationMessage(
            task_id=task.id,
            agent_id="user",
            role="user",
            message_type="user_message",
            phase="request",
            summary=contract.goal[:1000],
            content={"text": contract.goal},
            source_id=source_id,
        )
    )
    conversation.updated_at = datetime.now(UTC)
    if conversation.title == "新对话":
        conversation.title = contract.goal[:255]
    await session.commit()
    await request.app.state.coordinator.schedule(task.id)
    return ConversationTurnResponse(
        task_id=task.id,
        conversation_id=conversation_id,
        state=task.state,
    )


@router.get("/{conversation_id}/messages")
async def conversation_messages(
    conversation_id: UUID,
    session: Session,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> list[dict[str, Any]]:
    if await session.get(Conversation, conversation_id) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    messages = list(
        await session.scalars(
            select(ConversationMessage)
            .join(Task, Task.id == ConversationMessage.task_id)
            .where(
                Task.conversation_id == conversation_id,
                ConversationMessage.id > after,
            )
            .order_by(ConversationMessage.id)
            .limit(limit)
        )
    )
    return [
        {
            "id": message.id,
            "task_id": message.task_id,
            "agent_id": message.agent_id,
            "role": message.role,
            "message_type": message.message_type,
            "phase": message.phase,
            "summary": message.summary,
            "content": message.content,
            "source_id": message.source_id,
            "created_at": message.created_at,
        }
        for message in messages
    ]


@router.get("/{conversation_id}/stream")
async def stream_conversation(
    conversation_id: UUID,
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        cursor = after
        while not await request.is_disconnected():
            async with request.app.state.database.session_factory() as stream_session:
                exists = await stream_session.get(Conversation, conversation_id)
                if exists is None:
                    yield "event: error\ndata: {\"detail\":\"conversation not found\"}\n\n"
                    return
                rows = list(
                    await stream_session.scalars(
                        select(ConversationMessage)
                        .join(Task, Task.id == ConversationMessage.task_id)
                        .where(
                            Task.conversation_id == conversation_id,
                            ConversationMessage.id > cursor,
                        )
                        .order_by(ConversationMessage.id)
                    )
                )
            for message in rows:
                cursor = message.id
                payload = {
                    "id": message.id,
                    "task_id": str(message.task_id),
                    "agent_id": message.agent_id,
                    "role": message.role,
                    "message_type": message.message_type,
                    "phase": message.phase,
                    "summary": message.summary,
                    "content": message.content,
                    "source_id": message.source_id,
                    "created_at": message.created_at.isoformat(),
                }
                yield f"event: message\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if not rows:
                yield ": keepalive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream")
