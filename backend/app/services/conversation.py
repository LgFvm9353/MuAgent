from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import ConversationMessage
from app.orchestrator.scheduler import AgentInvocation

ConversationSink = Callable[[AgentInvocation], Awaitable[None]]


class ConversationService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    def sink(self, task_id: UUID) -> ConversationSink:
        async def publish(invocation: AgentInvocation) -> None:
            summary, content = format_agent_message(invocation.agent_id, invocation.output)
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


def format_agent_message(
    agent_id: str,
    output: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    if agent_id == "analyst":
        summary = str(output.get("summary") or "Analyst 已完成任务分析。")
    elif agent_id == "planner":
        steps = output.get("steps")
        count = len(steps) if isinstance(steps, list) else 0
        summary = f"Planner 生成了包含 {count} 个步骤的执行计划。"
    elif agent_id == "verifier":
        verdict = str(output.get("verdict") or "unknown")
        summary = f"Verifier 验证结论: {verdict}。"
    else:
        summary = f"{agent_id} 已完成发言。"
    return summary, output
