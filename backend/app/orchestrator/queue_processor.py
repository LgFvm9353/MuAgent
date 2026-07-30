import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.mentions import parse_action_mentions
from app.agents.runtime import StructuredGateway
from app.config import Settings
from app.contracts.agents import AgentHandoff, ChatAgentReply
from app.errors import safe_error_summary
from app.harness.context import AgentContextBuilder
from app.harness.registry import AgentRegistry
from app.models import (
    AgentInvocationQueueEntry,
    AgentRun,
    ConversationMessage,
    HandoffRecord,
)
from app.orchestrator.collaboration_guard import CollaborationGuard, CollaborationLimits
from app.orchestrator.invocation_queue import InvocationQueueRepository, InvocationRequest
from app.services.mention_execution import MentionExecutionService

ResultT = TypeVar("ResultT")


class QueueProcessor:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        gateway: StructuredGateway,
        agents: AgentRegistry,
        settings: Settings,
        schedule_task: Callable[[UUID], Awaitable[None]],
        *,
        lease_seconds: float = 120,
    ) -> None:
        self._sessions = sessions
        self._gateway = gateway
        self._agents = agents
        self._settings = settings
        self._schedule_task = schedule_task
        self._lease_seconds = lease_seconds
        self._owner = f"processor:{uuid4()}"

    async def drain(self) -> None:
        while True:
            async with self._sessions() as session:
                entries = await InvocationQueueRepository(session).claim_ready(
                    lease_owner=self._owner,
                    lease_seconds=self._lease_seconds,
                )
                await session.commit()
            if not entries:
                return
            async with asyncio.TaskGroup() as group:
                for entry in entries:
                    group.create_task(self._execute(entry.id), name=f"invocation:{entry.id}")

    async def _execute(self, entry_id: UUID) -> None:
        try:
            entry, run_id, context = await self._start(entry_id)
            if entry.intent == "execute":
                task_id = await self._bridge_execute(entry_id, run_id)
                await self._schedule_task(task_id)
                return
            definition = self._agents.get(entry.target_agent_id)
            result = await self._with_lease_heartbeat(
                entry.id,
                self._gateway.structured(
                    model=definition.model,
                    system=self._agents.prompt(entry.target_agent_id),
                    user_content=json.dumps(context, ensure_ascii=False, sort_keys=True),
                    output_model=ChatAgentReply,
                ),
            )
            if result.parsed_output is None:
                raise RuntimeError("agent returned no chat reply")
            reply = ChatAgentReply.model_validate(result.parsed_output)
            await self._finish(entry_id, run_id, reply)
        except asyncio.CancelledError:
            await self._fail(entry_id, "cancelled", "cancelled")
            raise
        except Exception as error:
            error_code, _ = safe_error_summary(error)
            await self._fail(entry_id, "failed", error_code)

    async def _with_lease_heartbeat(self, entry_id: UUID, operation: Awaitable[ResultT]) -> ResultT:
        task = asyncio.ensure_future(operation)
        interval = max(1.0, self._lease_seconds / 3)
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=interval)
                if task in done:
                    return task.result()
                async with self._sessions() as session:
                    await InvocationQueueRepository(session).renew(
                        entry_id,
                        lease_owner=self._owner,
                        lease_seconds=self._lease_seconds,
                    )
                    await session.commit()
        except BaseException:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            raise

    async def _start(
        self, entry_id: UUID
    ) -> tuple[AgentInvocationQueueEntry, UUID, dict[str, object]]:
        async with self._sessions() as session:
            entry = await session.get(AgentInvocationQueueEntry, entry_id)
            if entry is None or entry.status != "processing" or entry.lease_owner != self._owner:
                raise RuntimeError("invocation is not owned by processor")
            definition = self._agents.get(entry.target_agent_id)
            parent_run_id = None
            if entry.parent_invocation_id is not None:
                parent_run_id = await session.scalar(
                    select(AgentRun.id).where(
                        AgentRun.invocation_queue_entry_id == entry.parent_invocation_id
                    )
                )
            run = AgentRun(
                turn_id=entry.turn_id,
                task_id=entry.task_id,
                handoff_id=entry.handoff_id,
                invocation_queue_entry_id=entry.id,
                parent_run_id=parent_run_id,
                intent=entry.intent,
                agent_id=entry.target_agent_id,
                prompt_version=definition.prompt_version,
                schema_version=definition.schema_version,
                model=definition.model,
                config_hash=definition.config_hash(),
                status="running",
                started_at=datetime.now(UTC),
            )
            session.add(run)
            source_message = await session.get(ConversationMessage, entry.source_message_id)
            history_rows = list(
                await session.scalars(
                    select(ConversationMessage)
                    .where(ConversationMessage.conversation_id == entry.conversation_id)
                    .order_by(ConversationMessage.id.desc())
                    .limit(20)
                )
            )
            context = AgentContextBuilder().handoff_context(
                agent_id=entry.target_agent_id,
                source_agent_id=entry.source_agent_id,
                intent=entry.intent,
                objective=entry.objective,
                source_message=_message_context(source_message),
                relevant_history=tuple(_message_context(item) for item in reversed(history_rows)),
                depth=entry.depth,
                teammates=tuple(
                    {
                        "agent_id": item.agent_id,
                        "display_name": item.display_name,
                        "capabilities": sorted(item.capabilities),
                    }
                    for item in self._agents.all()
                    if item.agent_id != entry.target_agent_id
                ),
                allowed_handoff_targets=tuple(sorted(definition.handoff_targets)),
            )
            await session.commit()
            return entry, run.id, context

    async def _bridge_execute(self, entry_id: UUID, run_id: UUID) -> UUID:
        async with self._sessions() as session:
            entry = await session.get(AgentInvocationQueueEntry, entry_id)
            run = await session.get(AgentRun, run_id)
            if entry is None or run is None:
                raise LookupError(str(entry_id))
            result = await MentionExecutionService(session, self._settings).create_task(entry, run)
            run.status = "completed"
            run.output = {
                "task_id": str(result.task_id),
                "status": "controlled_execution_started",
            }
            run.completed_at = datetime.now(UTC)
            await InvocationQueueRepository(session).complete(entry.id, lease_owner=self._owner)
            await session.commit()
            return result.task_id

    async def _finish(self, entry_id: UUID, run_id: UUID, reply: ChatAgentReply) -> None:
        async with self._sessions() as session:
            entry = await session.get(AgentInvocationQueueEntry, entry_id)
            run = await session.get(AgentRun, run_id)
            if entry is None or run is None:
                raise LookupError(str(entry_id))
            message = ConversationMessage(
                task_id=entry.task_id,
                conversation_id=entry.conversation_id,
                turn_id=entry.turn_id,
                agent_run_id=run.id,
                handoff_id=entry.handoff_id,
                reply_to_message_id=entry.source_message_id,
                agent_id=entry.target_agent_id,
                role="agent",
                message_type="agent_message",
                phase="discussion",
                summary=reply.text[:1000],
                content=reply.model_dump(mode="json"),
                mentions=[item.target_agent_id for item in reply.handoffs],
                source_id=f"agent-run:{run.id}",
            )
            session.add(message)
            await session.flush()
            run.status = "completed"
            run.output = reply.model_dump(mode="json")
            run.completed_at = datetime.now(UTC)
            if entry.handoff_id is not None:
                handoff = await session.get(HandoffRecord, entry.handoff_id)
                if handoff is not None:
                    handoff.status = "completed"
                    handoff.completed_message_id = message.id
            handoffs = _merge_handoffs(
                reply.handoffs,
                parse_action_mentions(
                    reply.text,
                    registry=self._agents,
                    source_agent_id=entry.target_agent_id,
                ).handoffs,
            )
            source_definition = self._agents.get(entry.target_agent_id)
            for handoff_contract in handoffs[: source_definition.max_handoff_targets]:
                try:
                    await self._enqueue_handoff(session, entry, message, handoff_contract)
                except ValueError:
                    continue
            await InvocationQueueRepository(session).complete(entry.id, lease_owner=self._owner)
            await session.commit()

    async def _enqueue_handoff(
        self,
        session: AsyncSession,
        parent: AgentInvocationQueueEntry,
        source_message: ConversationMessage,
        contract: AgentHandoff,
    ) -> None:
        await CollaborationGuard(
            session,
            CollaborationLimits(
                max_depth=self._settings.max_handoff_depth,
                max_thread_invocations=self._settings.max_thread_invocations,
                max_ping_pong_streak=self._settings.max_ping_pong_streak,
            ),
        ).validate_next(parent, target_agent_id=contract.target_agent_id)
        self._agents.validate_handoff(
            parent.target_agent_id, contract.target_agent_id, contract.intent
        )
        handoff = HandoffRecord(
            turn_id=parent.turn_id,
            source_agent_id=parent.target_agent_id,
            target_agent_id=contract.target_agent_id,
            intent=contract.intent,
            objective=contract.objective,
            context_summary=contract.context_summary,
            source_message_id=source_message.id,
            parent_handoff_id=parent.handoff_id,
            depth=parent.depth + 1,
            status="queued",
        )
        session.add(handoff)
        await session.flush()
        await InvocationQueueRepository(session).enqueue(
            InvocationRequest(
                conversation_id=parent.conversation_id,
                turn_id=parent.turn_id,
                task_id=parent.task_id,
                source_agent_id=parent.target_agent_id,
                target_agent_id=contract.target_agent_id,
                source_message_id=source_message.id,
                handoff_id=handoff.id,
                parent_invocation_id=parent.id,
                intent=contract.intent,
                objective=contract.objective,
                depth=parent.depth + 1,
            )
        )

    async def _fail(self, entry_id: UUID, status: str, error_type: str) -> None:
        async with self._sessions() as session:
            entry = await session.get(AgentInvocationQueueEntry, entry_id)
            if entry is None or entry.status != "processing" or entry.lease_owner != self._owner:
                return
            run = await session.scalar(
                select(AgentRun).where(AgentRun.invocation_queue_entry_id == entry_id)
            )
            if run is not None:
                run.status = status
                run.error_type = error_type
                run.completed_at = datetime.now(UTC)
            await InvocationQueueRepository(session).complete(
                entry_id,
                lease_owner=self._owner,
                status=status,
                error_type=error_type,
            )
            await session.commit()


def _message_context(message: ConversationMessage | None) -> dict[str, object] | None:
    if message is None:
        return None
    return {
        "id": message.id,
        "role": message.role,
        "agent_id": message.agent_id,
        "summary": message.summary,
        "content": message.content,
    }


def _merge_handoffs(
    structured: tuple[AgentHandoff, ...], parsed: tuple[AgentHandoff, ...]
) -> tuple[AgentHandoff, ...]:
    merged: list[AgentHandoff] = []
    seen: set[str] = set()
    for handoff in (*structured, *parsed):
        if handoff.target_agent_id in seen:
            continue
        seen.add(handoff.target_agent_id)
        merged.append(handoff)
    return tuple(merged)
