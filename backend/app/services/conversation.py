from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.runtime import AgentInvocation
from app.models import ConversationMessage, Task

ConversationSink = Callable[[AgentInvocation], Awaitable[None]]


class DatabaseConversationStore:
    """Database-backed transcript adapter used by orchestration services."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def relevant_history(self, conversation_id: UUID, *, before_id: int | None = None) -> tuple[dict[str, Any], ...]:
        async with self._sessions() as session:
            query = select(ConversationMessage).where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.message_type.in_({"user_message", "agent_message", "parallel_result"}),
            ).order_by(ConversationMessage.id.desc()).limit(24)
            if before_id is not None:
                query = query.where(ConversationMessage.id < before_id)
            return build_relevant_history(list(await session.scalars(query)))

    async def append(self, conversation_id: UUID, *, agent_id: str, role: str,
                     message_type: str, phase: str, summary: str,
                     content: dict[str, Any], source_id: str,
                     task_id: UUID | None = None, turn_id: UUID | None = None,
                     agent_run_id: UUID | None = None, mentions: list[str] | None = None,
                     routing_metadata: dict[str, Any] | None = None,
                     reply_to_message_id: int | None = None) -> dict[str, Any]:
        async with self._sessions() as session:
            existing = await session.scalar(select(ConversationMessage).where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.source_id == source_id,
            ))
            if existing is not None:
                return {"id": existing.id, "source_id": existing.source_id}
            row = ConversationMessage(
                conversation_id=conversation_id, task_id=task_id, turn_id=turn_id,
                agent_run_id=agent_run_id, agent_id=agent_id, role=role,
                message_type=message_type, phase=phase, summary=summary[:1000],
                content=content, source_id=source_id, mentions=mentions or [],
                routing_metadata=routing_metadata or {}, reply_to_message_id=reply_to_message_id,
            )
            session.add(row)
            await session.commit()
            return {"id": row.id, "source_id": row.source_id}

    async def find_by_source(self, conversation_id: UUID, source_id: str) -> dict[str, Any] | None:
        async with self._sessions() as session:
            row = await session.scalar(select(ConversationMessage).where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.source_id == source_id,
            ))
            return {"id": row.id, "source_id": row.source_id} if row is not None else None


class ConversationService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def relevant_history(
        self, conversation_id: UUID, current_turn_id: UUID
    ) -> tuple[dict[str, Any], ...]:
        async with self._sessions() as session:
            current_message_id = await session.scalar(
                select(func.min(ConversationMessage.id)).where(
                    ConversationMessage.conversation_id == conversation_id,
                    ConversationMessage.turn_id == current_turn_id,
                    ConversationMessage.message_type == "user_message",
                )
            )
            if current_message_id is None:
                return ()
            messages = list(
                await session.scalars(
                    select(ConversationMessage)
                    .where(
                        ConversationMessage.conversation_id == conversation_id,
                        ConversationMessage.id < current_message_id,
                        ConversationMessage.message_type.in_({"user_message", "agent_message", "parallel_result"}),
                    )
                    .order_by(ConversationMessage.id.desc())
                    .limit(24)
                )
            )
        return build_relevant_history(messages)

    def sink(self, task_id: UUID) -> ConversationSink:
        async def publish(invocation: AgentInvocation) -> None:
            summary, content = format_agent_message(invocation.agent_id, invocation.output, invocation.phase)
            async with self._sessions() as session:
                task = await session.get(Task, task_id)
                if task is None:
                    return
                session.add(
                    ConversationMessage(
                        task_id=task_id,
                        conversation_id=task.conversation_id,
                        turn_id=None,
                        agent_id=invocation.agent_id,
                        role="agent",
                        message_type=invocation.message_type,
                        phase=invocation.phase,
                        summary=summary[:1000],
                        content=content,
                        source_id=invocation.source_id,
                    )
                )
                await session.commit()
        return publish


def format_agent_message(agent_id: str, output: dict[str, Any], phase: str = "discussion") -> tuple[str, dict[str, Any]]:
    explicit = output.get("summary")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip(), output
    if agent_id == "reviewer" and phase == "verification":
        return f"Reviewer verification verdict: {output.get('verdict', 'unknown')}.", output
    return f"{agent_id} completed a response.", output


def build_relevant_history(newest_first: list[Any]) -> tuple[dict[str, Any], ...]:
    selected: list[dict[str, Any]] = []
    total = 0
    for message in newest_first:
        if message.message_type not in {"user_message", "agent_message", "parallel_result"}:
            continue
        content = message.content
        text = content.get("text") if isinstance(content, dict) else None
        if not isinstance(text, str) or not text.strip():
            continue
        text = text.strip()[:8000]
        if total + len(text) > 24000:
            text = text[: 24000 - total]
        if not text:
            break
        selected.append({"message_id": message.id, "role": message.role, "agent_id": message.agent_id, "text": text})
        total += len(text)
        if len(selected) >= 12 or total >= 24000:
            break
    selected.reverse()
    return tuple(selected)
