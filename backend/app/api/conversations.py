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
from app.contracts.collaboration import CollaborationMode
from app.contracts.conversation import (
    AgentRunResponse,
    ConversationCreate,
    ConversationResponse,
    ConversationTurnCreate,
    ConversationTurnResponse,
)
from app.models import (
    AgentRun,
    Conversation,
    ConversationMessage,
    ConversationTurn,
    RoutingDecision,
    Task,
)
from app.orchestrator.state_machine import TERMINAL_STATES
from app.repositories import TaskRepository

router = APIRouter(prefix="/conversations", tags=["conversations"])
Session = Annotated[AsyncSession, Depends(database_session)]
_TERMINAL_VALUES = {state.value for state in TERMINAL_STATES}


def _response(conversation: Conversation, latest: Task | None = None) -> ConversationResponse:
    return ConversationResponse(id=conversation.id, title=conversation.title, created_at=conversation.created_at,
        updated_at=conversation.updated_at, latest_task_id=latest.id if latest else None,
        latest_task_state=latest.state if latest else None)


async def _latest_task(session: AsyncSession, conversation_id: UUID) -> Task | None:
    return await session.scalar(select(Task).where(Task.conversation_id == conversation_id).order_by(Task.created_at.desc()).limit(1))


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(payload: ConversationCreate, session: Session) -> ConversationResponse:
    conversation = Conversation(title=payload.title.strip())
    session.add(conversation)
    await session.commit(); await session.refresh(conversation)
    return _response(conversation)


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(session: Session, limit: Annotated[int, Query(ge=1, le=100)] = 50,
                             offset: Annotated[int, Query(ge=0)] = 0) -> list[ConversationResponse]:
    conversations = list(await session.scalars(select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit).offset(offset)))
    return [_response(item, await _latest_task(session, item.id)) for item in conversations]


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(conversation_id: UUID, session: Session) -> ConversationResponse:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None: raise HTTPException(404, "conversation not found")
    return _response(conversation, await _latest_task(session, conversation_id))


@router.post("/{conversation_id}/messages", response_model=ConversationTurnResponse, status_code=status.HTTP_201_CREATED)
async def create_turn(conversation_id: UUID, payload: ConversationTurnCreate, session: Session, request: Request) -> ConversationTurnResponse:
    conversation = await session.scalar(select(Conversation).where(Conversation.id == conversation_id).with_for_update())
    if conversation is None: raise HTTPException(404, "conversation not found")
    existing_turn = await session.scalar(select(ConversationTurn).where(ConversationTurn.conversation_id == conversation_id, ConversationTurn.idempotency_key == payload.idempotency_key))
    if existing_turn is not None:
        runs = list(await session.scalars(select(AgentRun).where(AgentRun.turn_id == existing_turn.id)))
        return ConversationTurnResponse(turn_id=existing_turn.id, conversation_id=conversation_id, state=existing_turn.status,
            collaboration_mode=CollaborationMode(existing_turn.collaboration_mode), synthesize=existing_turn.synthesize,
            selected_agents=tuple(run.agent_id for run in runs), agent_runs=tuple(AgentRunResponse(id=run.id, agent_id=run.agent_id, model=run.model, status=run.status) for run in runs))
    source_id = f"user:{payload.idempotency_key}"
    if payload.text is not None:
        decision = request.app.state.coordinator.route_chat(payload.text)
        mode = CollaborationMode.SINGLE
        recommended_agents = decision.agent_ids
        targets = ("supervisor",)
        if not targets: raise HTTPException(422, "no enabled agent matched the request")
        turn = ConversationTurn(conversation_id=conversation_id, idempotency_key=payload.idempotency_key,
            status="running", collaboration_mode=mode.value, collaboration_phase=mode.value,
            synthesize=False, requires_execution=decision.requires_execution)
        session.add(turn); await session.flush()
        route = RoutingDecision(turn_id=turn.id, source=decision.source, selected_agents=list(recommended_agents), confidence=decision.confidence, reason_code=decision.reason_code, mentions=list(decision.mentions))
        session.add(route)
        message = ConversationMessage(conversation_id=conversation_id, turn_id=turn.id, routing_decision_id=route.id,
            agent_id="user", role="user", message_type="user_message", phase="request", summary=payload.text[:1000],
            content={"text": payload.text}, mentions=list(decision.mentions), routing_metadata={"source": decision.source, "confidence": decision.confidence, "reason_code": decision.reason_code, "mode": mode.value}, source_id=source_id)
        session.add(message); conversation.updated_at = datetime.now(UTC)
        if conversation.title == "新对话": conversation.title = payload.text[:255]
        await session.commit()
        runs = []
        for agent_id in targets:
            definition = request.app.state.coordinator.agent_definition(agent_id)
            run = AgentRun(turn_id=turn.id, agent_id=agent_id, intent=mode.value, phase=mode.value, role=definition.role,
                prompt_version=definition.prompt_version, schema_version=definition.schema_version, model=definition.model,
                config_hash=definition.config_hash(), status="queued", skill_id=payload.skill_id)
            runs.append(run); session.add(run)
        await session.commit()
        await request.app.state.coordinator.schedule_chat(runs[0].id, payload.text, conversation_id=conversation_id, turn_id=turn.id, recommended_agents=tuple(recommended_agents))
        return ConversationTurnResponse(turn_id=turn.id, conversation_id=conversation_id, state=turn.status, route_source=decision.source,
            collaboration_mode=mode, synthesize=False, selected_agents=tuple(targets),
            agent_runs=tuple(AgentRunResponse(id=run.id, agent_id=run.agent_id, model=run.model, status=run.status) for run in runs))
    contract = payload.contract; assert contract is not None
    latest = await _latest_task(session, conversation_id)
    if latest is not None and latest.state not in _TERMINAL_VALUES: raise HTTPException(409, "conversation_busy")
    task = Task(id=contract.task_id, conversation_id=conversation_id, trace_id=payload.idempotency_key, contract=contract.model_dump(mode="json"))
    await TaskRepository(session).add(task); await session.flush()
    session.add(ConversationMessage(task_id=task.id, conversation_id=conversation_id, agent_id="user", role="user", message_type="user_message", phase="request", summary=contract.goal[:1000], content={"text": contract.goal}, source_id=source_id))
    conversation.updated_at = datetime.now(UTC)
    if conversation.title == "新对话": conversation.title = contract.goal[:255]
    await session.commit(); await request.app.state.coordinator.schedule(task.id)
    return ConversationTurnResponse(task_id=task.id, conversation_id=conversation_id, state=task.state)


def _message_payload(message: ConversationMessage) -> dict[str, Any]:
    return {"id": message.id, "task_id": message.task_id, "conversation_id": message.conversation_id, "turn_id": message.turn_id, "agent_run_id": message.agent_run_id, "routing_decision_id": message.routing_decision_id, "reply_to_message_id": message.reply_to_message_id, "agent_id": message.agent_id, "role": message.role, "message_type": message.message_type, "phase": message.phase, "summary": message.summary, "content": message.content, "mentions": message.mentions, "routing_metadata": message.routing_metadata, "source_id": message.source_id, "created_at": message.created_at}


@router.get("/{conversation_id}/messages")
async def conversation_messages(conversation_id: UUID, session: Session, after: Annotated[int, Query(ge=0)] = 0,
                                limit: Annotated[int, Query(ge=1, le=1000)] = 500) -> list[dict[str, Any]]:
    if await session.get(Conversation, conversation_id) is None: raise HTTPException(404, "conversation not found")
    rows = list(await session.scalars(select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id, ConversationMessage.id > after).order_by(ConversationMessage.id).limit(limit)))
    return [_message_payload(row) for row in rows]


@router.get("/{conversation_id}/stream")
async def stream_conversation(conversation_id: UUID, request: Request, after: Annotated[int, Query(ge=0)] = 0) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        cursor = after
        while not await request.is_disconnected():
            async with request.app.state.database.session_factory() as session:
                if await session.get(Conversation, conversation_id) is None:
                    yield 'event: error\ndata: {"detail":"conversation not found"}\n\n'; return
                rows = list(await session.scalars(select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id, ConversationMessage.id > cursor).order_by(ConversationMessage.id)))
            for row in rows:
                cursor = row.id
                yield f"event: message\ndata: {json.dumps(_message_payload(row), default=str, ensure_ascii=False)}\n\n"
            if not rows: yield ": keepalive\n\n"
            await asyncio.sleep(request.app.state.settings.sse_poll_interval_seconds)
    return StreamingResponse(events(), media_type="text/event-stream")
