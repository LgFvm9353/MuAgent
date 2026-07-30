from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentInvocationQueueEntry


@dataclass(frozen=True, slots=True)
class CollaborationLimits:
    max_depth: int
    max_thread_invocations: int
    max_ping_pong_streak: int


class CollaborationGuard:
    def __init__(self, session: AsyncSession, limits: CollaborationLimits) -> None:
        self._session = session
        self._limits = limits

    async def validate_next(
        self,
        parent: AgentInvocationQueueEntry,
        *,
        target_agent_id: str,
    ) -> None:
        if parent.depth + 1 > self._limits.max_depth:
            raise ValueError("maximum agent handoff depth exceeded")
        invocation_count = await self._session.scalar(
            select(func.count(AgentInvocationQueueEntry.id)).where(
                AgentInvocationQueueEntry.conversation_id == parent.conversation_id
            )
        )
        if int(invocation_count or 0) >= self._limits.max_thread_invocations:
            raise ValueError("maximum thread invocation count exceeded")
        if (
            await self._ping_pong_streak(parent, target_agent_id)
            >= self._limits.max_ping_pong_streak
        ):
            raise ValueError("agent handoff ping-pong limit exceeded")

    async def _ping_pong_streak(
        self, parent: AgentInvocationQueueEntry, target_agent_id: str
    ) -> int:
        streak = 1
        current = parent
        expected_source = parent.target_agent_id
        expected_target = target_agent_id
        while current.parent_invocation_id is not None:
            ancestor = await self._session.get(
                AgentInvocationQueueEntry, current.parent_invocation_id
            )
            if ancestor is None:
                break
            if (
                ancestor.target_agent_id != expected_target
                or current.target_agent_id != expected_source
            ):
                break
            streak += 1
            expected_source, expected_target = expected_target, expected_source
            current = ancestor
        return streak
