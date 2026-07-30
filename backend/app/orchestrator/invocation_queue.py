import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentInvocationQueueEntry, Conversation

TERMINAL_INVOCATION_STATUSES = frozenset({"completed", "failed", "cancelled", "superseded"})


@dataclass(frozen=True, slots=True)
class InvocationRequest:
    conversation_id: UUID
    turn_id: UUID
    target_agent_id: str
    intent: str
    objective: str
    source_agent_id: str | None = None
    task_id: UUID | None = None
    source_message_id: int | None = None
    handoff_id: UUID | None = None
    parent_invocation_id: UUID | None = None
    depth: int = 0
    priority: int = 0

    def dedup_key(self) -> str:
        payload = {
            "conversation_id": str(self.conversation_id),
            "turn_id": str(self.turn_id),
            "source_message_id": self.source_message_id,
            "target_agent_id": self.target_agent_id,
            "intent": self.intent,
            "objective": self.objective.strip(),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class InvocationQueueRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(self, request: InvocationRequest) -> AgentInvocationQueueEntry:
        await self._session.scalar(
            select(Conversation.id)
            .where(Conversation.id == request.conversation_id)
            .with_for_update()
        )
        key = request.dedup_key()
        existing = await self._session.scalar(
            select(AgentInvocationQueueEntry).where(AgentInvocationQueueEntry.dedup_key == key)
        )
        if existing is not None:
            return existing
        entry = AgentInvocationQueueEntry(
            conversation_id=request.conversation_id,
            turn_id=request.turn_id,
            task_id=request.task_id,
            source_agent_id=request.source_agent_id,
            target_agent_id=request.target_agent_id,
            source_message_id=request.source_message_id,
            handoff_id=request.handoff_id,
            parent_invocation_id=request.parent_invocation_id,
            intent=request.intent,
            objective=request.objective.strip(),
            depth=request.depth,
            priority=request.priority,
            dedup_key=key,
            status="queued",
        )
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def claim_ready(
        self,
        *,
        lease_owner: str,
        lease_seconds: float,
        limit: int = 16,
    ) -> list[AgentInvocationQueueEntry]:
        now = datetime.now(UTC)
        conversation_ids = list(
            await self._session.scalars(
                select(AgentInvocationQueueEntry.conversation_id)
                .where(
                    AgentInvocationQueueEntry.status == "queued",
                    AgentInvocationQueueEntry.available_at <= now,
                )
                .distinct()
                .limit(limit)
            )
        )
        if not conversation_ids:
            return []
        locked_conversation_ids = list(
            await self._session.scalars(
                select(Conversation.id)
                .where(Conversation.id.in_(conversation_ids))
                .with_for_update(skip_locked=True)
            )
        )
        if not locked_conversation_ids:
            return []
        candidates = list(
            await self._session.scalars(
                select(AgentInvocationQueueEntry)
                .where(
                    AgentInvocationQueueEntry.conversation_id.in_(locked_conversation_ids),
                    AgentInvocationQueueEntry.status == "queued",
                    AgentInvocationQueueEntry.available_at <= now,
                )
                .order_by(
                    AgentInvocationQueueEntry.priority.desc(),
                    AgentInvocationQueueEntry.created_at,
                )
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        )
        claimed: list[AgentInvocationQueueEntry] = []
        occupied_slots: set[tuple[UUID, str]] = set()
        for entry in candidates:
            slot = (entry.conversation_id, entry.target_agent_id)
            if slot in occupied_slots or await self._slot_is_processing(*slot):
                continue
            entry.status = "processing"
            entry.attempt += 1
            entry.lease_owner = lease_owner
            entry.lease_expires_at = now + timedelta(seconds=lease_seconds)
            entry.started_at = entry.started_at or now
            claimed.append(entry)
            occupied_slots.add(slot)
        await self._session.flush()
        return claimed

    async def renew(
        self,
        entry_id: UUID,
        *,
        lease_owner: str,
        lease_seconds: float,
    ) -> None:
        entry = await self._session.scalar(
            select(AgentInvocationQueueEntry)
            .where(AgentInvocationQueueEntry.id == entry_id)
            .with_for_update()
        )
        if entry is None or entry.status != "processing" or entry.lease_owner != lease_owner:
            raise RuntimeError("invocation lease is not owned by caller")
        entry.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
        await self._session.flush()

    async def recover_expired(self) -> int:
        now = datetime.now(UTC)
        entries = list(
            await self._session.scalars(
                select(AgentInvocationQueueEntry)
                .where(
                    AgentInvocationQueueEntry.status == "processing",
                    AgentInvocationQueueEntry.lease_expires_at < now,
                )
                .with_for_update(skip_locked=True)
            )
        )
        for entry in entries:
            entry.status = "queued"
            entry.lease_owner = None
            entry.lease_expires_at = None
            entry.available_at = now
        await self._session.flush()
        return len(entries)

    async def complete(
        self,
        entry_id: UUID,
        *,
        lease_owner: str,
        status: str = "completed",
        error_type: str | None = None,
    ) -> AgentInvocationQueueEntry:
        if status not in TERMINAL_INVOCATION_STATUSES:
            raise ValueError(f"invalid terminal invocation status: {status}")
        entry = await self._session.scalar(
            select(AgentInvocationQueueEntry)
            .where(AgentInvocationQueueEntry.id == entry_id)
            .with_for_update()
        )
        if entry is None:
            raise LookupError(str(entry_id))
        if entry.status != "processing" or entry.lease_owner != lease_owner:
            raise RuntimeError("invocation lease is not owned by caller")
        entry.status = status
        entry.error_type = error_type
        entry.completed_at = datetime.now(UTC)
        entry.lease_owner = None
        entry.lease_expires_at = None
        await self._session.flush()
        return entry

    async def _slot_is_processing(self, conversation_id: UUID, target_agent_id: str) -> bool:
        existing = await self._session.scalar(
            select(AgentInvocationQueueEntry.id)
            .where(
                AgentInvocationQueueEntry.conversation_id == conversation_id,
                AgentInvocationQueueEntry.target_agent_id == target_agent_id,
                AgentInvocationQueueEntry.status == "processing",
                or_(
                    AgentInvocationQueueEntry.lease_expires_at.is_(None),
                    AgentInvocationQueueEntry.lease_expires_at > datetime.now(UTC),
                ),
            )
            .limit(1)
        )
        return existing is not None
