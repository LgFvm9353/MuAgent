from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import ConversationMessage
from app.orchestrator.scheduler import AgentInvocation

ConversationSink = Callable[[AgentInvocation], Awaitable[None]]

_HISTORY_MESSAGE_TYPES = frozenset({"user_message", "agent_message"})
_HISTORY_MAX_MESSAGES = 12
_HISTORY_MAX_MESSAGE_CHARS = 8_000
_HISTORY_MAX_TOTAL_CHARS = 24_000


class ConversationService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def relevant_history(
        self,
        conversation_id: UUID,
        current_turn_id: UUID,
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
                        ConversationMessage.message_type.in_(_HISTORY_MESSAGE_TYPES),
                    )
                    .order_by(ConversationMessage.id.desc())
                    .limit(_HISTORY_MAX_MESSAGES * 2)
                )
            )
        return build_relevant_history(messages)

    def sink(self, task_id: UUID) -> ConversationSink:
        async def publish(invocation: AgentInvocation) -> None:
            summary, content = format_agent_message(
                invocation.agent_id,
                invocation.output,
                invocation.phase,
            )
            async with self._sessions() as session:
                session.add(
                    ConversationMessage(
                        task_id=task_id,
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


def build_relevant_history(
    newest_first: list[ConversationMessage],
) -> tuple[dict[str, Any], ...]:
    selected: list[dict[str, Any]] = []
    total_chars = 0
    for message in newest_first:
        if message.message_type not in _HISTORY_MESSAGE_TYPES:
            continue
        text = message.content.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        text = text.strip()[:_HISTORY_MAX_MESSAGE_CHARS]
        if total_chars + len(text) > _HISTORY_MAX_TOTAL_CHARS:
            remaining = _HISTORY_MAX_TOTAL_CHARS - total_chars
            if remaining <= 0:
                break
            text = text[:remaining]
        selected.append(
            {
                "message_id": message.id,
                "role": message.role,
                "agent_id": message.agent_id,
                "text": text,
            }
        )
        total_chars += len(text)
        if len(selected) >= _HISTORY_MAX_MESSAGES or total_chars >= _HISTORY_MAX_TOTAL_CHARS:
            break
    selected.reverse()
    return tuple(selected)


def format_agent_message(
    agent_id: str,
    output: dict[str, Any],
    phase: str = "discussion",
) -> tuple[str, dict[str, Any]]:
    explicit_summary = output.get("summary")
    if isinstance(explicit_summary, str) and explicit_summary.strip():
        return explicit_summary.strip(), output
    if agent_id == "architect" and phase in {"planning", "replanning"}:
        steps = output.get("steps")
        count = len(steps) if isinstance(steps, list) else 0
        summary = f"Architect 生成了包含 {count} 个步骤的执行计划。"
    elif agent_id == "reviewer" and phase == "verification":
        verdict = str(output.get("verdict") or "unknown")
        summary = f"Reviewer 验证结论: {verdict}。"
    else:
        summary = f"{agent_id} 已完成发言。"
    return summary, output
