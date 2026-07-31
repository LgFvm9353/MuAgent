import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.runtime import StructuredGateway
from app.config import Settings
from app.contracts.agents import ChatAgentReply, ParallelSynthesisReply
from app.errors import safe_error_summary
from app.harness.context import AgentContextBuilder
from app.harness.registry import AgentRegistry
from app.models import (
    AgentInvocationQueueEntry,
    AgentRun,
    ConversationMessage,
    ParallelInvocationRequest,
)
from app.orchestrator.invocation_queue import InvocationQueueRepository
from app.orchestrator.parallel_invocations import ParallelInvocationService
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
        self._timeout_tasks: set[asyncio.Task[None]] = set()

    async def resume_timeouts(self) -> None:
        async with self._sessions() as session:
            await ParallelInvocationService(session, self._agents).recover_synthesis()
            deadlines = list(
                await session.scalars(
                    select(ParallelInvocationRequest.deadline_at).where(
                        ParallelInvocationRequest.status.not_in(
                            {"done", "timeout", "failed"}
                        )
                    )
                )
            )
            await session.commit()
        now = datetime.now(UTC)
        for deadline in deadlines:
            normalized = deadline if deadline.tzinfo is not None else deadline.replace(tzinfo=UTC)
            self._schedule_timeout(max(0.0, (normalized - now).total_seconds()))

    def _schedule_timeout(self, delay: float) -> None:
        task = asyncio.create_task(self._expire_after(delay), name="parallel-timeout")
        self._timeout_tasks.add(task)
        task.add_done_callback(self._timeout_tasks.discard)

    async def _expire_after(self, delay: float) -> None:
        await asyncio.sleep(delay)
        async with self._sessions() as session:
            await ParallelInvocationService(session, self._agents).expire_due()
            await session.commit()
        await self._synthesize_ready()

    async def close(self) -> None:
        tasks = tuple(self._timeout_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def drain(self) -> None:
        while True:
            async with self._sessions() as session:
                queue = InvocationQueueRepository(session)
                await queue.recover_expired()
                await ParallelInvocationService(session, self._agents).expire_due()
                entries = await queue.claim_ready(
                    lease_owner=self._owner,
                    lease_seconds=self._lease_seconds,
                )
                await session.commit()
            if not entries:
                await self._synthesize_ready()
                return
            async with asyncio.TaskGroup() as group:
                for entry in entries:
                    group.create_task(self._execute(entry.id), name=f"invocation:{entry.id}")
            await self._synthesize_ready()

    async def _synthesize_ready(self) -> None:
        async with self._sessions() as session:
            request_ids = await ParallelInvocationService(
                session, self._agents
            ).synthesizing_requests()
        for request_id in request_ids:
            await self._synthesize(request_id)

    async def _synthesize(self, request_id: UUID) -> None:
        async with self._sessions() as session:
            claimed = await ParallelInvocationService(session, self._agents).claim_synthesis(
                request_id
            )
            if claimed is None:
                return
            request, responses = claimed
            await session.commit()
        successful = [item for item in responses if item.status == "received" and item.content]
        if not successful:
            return
        synthesis_input = {
            "user_question": request.question,
            "agent_results": [
                {
                    "agent_id": item.target_agent_id,
                    "status": item.status,
                    "content": item.content,
                    "error_type": item.error_type,
                }
                for item in responses
            ],
            "instruction": (
                "Synthesize one clear final answer to the user. Preserve useful disagreements, "
                "do not invent missing agent results, and briefly identify failed or timed-out "
                "agents."
            ),
        }
        definition = self._agents.get("architect")
        result = await self._gateway.structured(
            model=definition.model,
            system=(
                "You are the system synthesis stage for parallel agent collaboration. "
                "Return only a grounded synthesis of the supplied agent results."
            ),
            user_content=json.dumps(synthesis_input, ensure_ascii=False, sort_keys=True),
            output_model=ParallelSynthesisReply,
        )
        if result.parsed_output is None:
            raise RuntimeError("parallel synthesis returned no output")
        reply = ParallelSynthesisReply.model_validate(result.parsed_output)
        async with self._sessions() as session:
            await ParallelInvocationService(session, self._agents).complete_synthesis(
                request_id, reply.text
            )
            await session.commit()

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
            run = AgentRun(
                turn_id=entry.turn_id,
                task_id=entry.task_id,
                invocation_queue_entry_id=entry.id,
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
            parallel_context = None
            if entry.parallel_request_id is not None:
                parallel_request = await session.get(
                    ParallelInvocationRequest, entry.parallel_request_id
                )
                if parallel_request is not None:
                    parallel_context = {
                        "request_id": str(parallel_request.id),
                        "initiator_agent_id": parallel_request.initiator_agent_id,
                        "callback_agent_id": parallel_request.callback_agent_id,
                        "question": parallel_request.question,
                        "context": parallel_request.context,
                        "anti_cascade": True,
                    }
            context = AgentContextBuilder().invocation_context(
                agent_id=entry.target_agent_id,
                source_agent_id=entry.source_agent_id,
                intent=entry.intent,
                objective=entry.objective,
                source_message=_message_context(source_message),
                relevant_history=tuple(_message_context(item) for item in reversed(history_rows)),
                teammates=tuple(
                    {
                        "agent_id": item.agent_id,
                        "display_name": item.display_name,
                        "capabilities": sorted(item.capabilities),
                    }
                    for item in self._agents.all()
                    if item.agent_id != entry.target_agent_id
                ),
                parallel=parallel_context,
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
                reply_to_message_id=entry.source_message_id,
                agent_id=entry.target_agent_id,
                role="agent",
                message_type="agent_message",
                phase="discussion",
                summary=reply.text[:1000],
                content={"text": reply.text},
                mentions=[],
                source_id=f"agent-run:{run.id}",
            )
            session.add(message)
            await session.flush()
            run.status = "completed"
            run.output = {"text": reply.text}
            run.completed_at = datetime.now(UTC)
            if entry.parallel_request_id is not None:
                await ParallelInvocationService(session, self._agents).record_success(
                    entry, {"text": reply.text}
                )
            await InvocationQueueRepository(session).complete(entry.id, lease_owner=self._owner)
            await session.commit()

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
            if entry.parallel_request_id is not None:
                await ParallelInvocationService(session, self._agents).record_failure(
                    entry, error_type
                )
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
