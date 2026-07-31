from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.harness.registry import AgentRegistry
from app.models import (
    AgentInvocationQueueEntry,
    Conversation,
    ConversationMessage,
    ConversationTurn,
    ParallelInvocationRequest,
    ParallelInvocationResponse,
)
from app.orchestrator.invocation_queue import InvocationQueueRepository, InvocationRequest

_TERMINAL_RESPONSE_STATUSES = frozenset({"received", "failed", "timeout"})
_TERMINAL_REQUEST_STATUSES = frozenset({"done", "timeout", "failed"})


class ParallelInvocationService:
    def __init__(
        self,
        session: AsyncSession,
        agents: AgentRegistry,
        inactivity_seconds: float = 120.0,
    ) -> None:
        self._session = session
        self._agents = agents
        self._inactivity_seconds = inactivity_seconds

    def _next_deadline(self, now: datetime | None = None) -> datetime:
        return (now or datetime.now(UTC)) + timedelta(seconds=self._inactivity_seconds)

    async def create(
        self,
        *,
        conversation_id: UUID,
        turn_id: UUID,
        source_message_id: int,
        targets: tuple[str, ...],
        question: str,
        idempotency_key: UUID,
    ) -> ParallelInvocationRequest:
        await self._session.scalar(
            select(Conversation.id)
            .where(Conversation.id == conversation_id)
            .with_for_update()
        )
        existing = await self._session.scalar(
            select(ParallelInvocationRequest).where(
                ParallelInvocationRequest.conversation_id == conversation_id,
                ParallelInvocationRequest.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing

        resolved_targets = tuple(self._agents.get(target).agent_id for target in targets)
        if len(resolved_targets) < 2 or len(resolved_targets) > 3:
            raise ValueError("parallel requests require 2-3 agents")
        if len(set(resolved_targets)) != len(resolved_targets):
            raise ValueError("parallel request targets must be unique")

        now = datetime.now(UTC)
        request = ParallelInvocationRequest(
            conversation_id=conversation_id,
            turn_id=turn_id,
            source_message_id=source_message_id,
            initiator_agent_id="user",
            callback_agent_id="system",
            targets=list(resolved_targets),
            question=question,
            context="",
            idempotency_key=idempotency_key,
            status="running",
            deadline_at=self._next_deadline(now),
        )
        self._session.add(request)
        await self._session.flush()

        queue = InvocationQueueRepository(self._session)
        for target in resolved_targets:
            response = ParallelInvocationResponse(
                request_id=request.id,
                target_agent_id=target,
                status="queued",
            )
            self._session.add(response)
            await self._session.flush()
            await queue.enqueue(
                InvocationRequest(
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    source_agent_id="user",
                    target_agent_id=target,
                    source_message_id=source_message_id,
                    intent="parallel",
                    objective=question,
                    parallel_request_id=request.id,
                    parallel_response_id=response.id,
                )
            )
        return request

    async def record_success(
        self, entry: AgentInvocationQueueEntry, content: dict[str, object]
    ) -> None:
        await self._record(entry, status="received", content=content)

    async def record_failure(self, entry: AgentInvocationQueueEntry, error_type: str) -> None:
        await self._record(entry, status="failed", error_type=error_type)

    async def _record(
        self,
        entry: AgentInvocationQueueEntry,
        *,
        status: str,
        content: dict[str, object] | None = None,
        error_type: str | None = None,
    ) -> None:
        if entry.parallel_response_id is None or entry.parallel_request_id is None:
            return
        response = await self._session.scalar(
            select(ParallelInvocationResponse)
            .where(ParallelInvocationResponse.id == entry.parallel_response_id)
            .with_for_update()
        )
        if response is None or response.status in _TERMINAL_RESPONSE_STATUSES:
            return
        now = datetime.now(UTC)
        response.status = status
        response.content = content
        response.error_type = error_type
        response.completed_at = now
        await self._converge(entry.parallel_request_id, now=now)

    async def expire_inactive(self) -> int:
        now = datetime.now(UTC)
        requests = list(
            await self._session.scalars(
                select(ParallelInvocationRequest)
                .where(
                    ParallelInvocationRequest.status.not_in(_TERMINAL_REQUEST_STATUSES),
                    ParallelInvocationRequest.deadline_at <= now,
                )
                .with_for_update(skip_locked=True)
            )
        )
        expired = 0
        for request in requests:
            active_entry = await self._session.scalar(
                select(AgentInvocationQueueEntry.id).where(
                    AgentInvocationQueueEntry.parallel_request_id == request.id,
                    AgentInvocationQueueEntry.status == "processing",
                    AgentInvocationQueueEntry.lease_expires_at.is_not(None),
                    AgentInvocationQueueEntry.lease_expires_at > now,
                )
            )
            if active_entry is not None:
                request.deadline_at = self._next_deadline(now)
                continue
            responses = list(
                await self._session.scalars(
                    select(ParallelInvocationResponse).where(
                        ParallelInvocationResponse.request_id == request.id
                    )
                )
            )
            for response in responses:
                if response.status not in _TERMINAL_RESPONSE_STATUSES:
                    response.status = "timeout"
                    response.completed_at = now
            request.deadline_at = self._next_deadline(now)
            expired += 1
            if any(response.status == "received" for response in responses):
                request.status = "synthesizing"
            else:
                request.status = "failed"
                request.completed_at = now
                await self._aggregate(request, responses)
        return expired

    async def touch(self, request_id: UUID) -> bool:
        request = await self._session.scalar(
            select(ParallelInvocationRequest)
            .where(ParallelInvocationRequest.id == request_id)
            .with_for_update()
        )
        if request is None or request.status in _TERMINAL_REQUEST_STATUSES:
            return False
        request.deadline_at = self._next_deadline()
        return True

    async def _converge(self, request_id: UUID, *, now: datetime | None = None) -> None:
        request = await self._session.scalar(
            select(ParallelInvocationRequest)
            .where(ParallelInvocationRequest.id == request_id)
            .with_for_update()
        )
        if request is None or request.status in _TERMINAL_REQUEST_STATUSES:
            return
        activity_at = now or datetime.now(UTC)
        request.deadline_at = self._next_deadline(activity_at)
        responses = list(
            await self._session.scalars(
                select(ParallelInvocationResponse).where(
                    ParallelInvocationResponse.request_id == request.id
                )
            )
        )
        terminal = sum(item.status in _TERMINAL_RESPONSE_STATUSES for item in responses)
        if terminal < len(responses):
            if terminal:
                request.status = "partial"
            return
        request.status = (
            "failed" if all(item.status == "failed" for item in responses) else "synthesizing"
        )
        if request.status == "failed":
            request.completed_at = activity_at
            await self._aggregate(request, responses)

    async def recover_synthesis(self) -> int:
        requests = list(
            await self._session.scalars(
                select(ParallelInvocationRequest)
                .where(ParallelInvocationRequest.status == "synthesis_running")
                .with_for_update(skip_locked=True)
            )
        )
        for request in requests:
            request.status = "synthesizing"
        return len(requests)

    async def synthesizing_requests(self) -> list[UUID]:
        return list(
            await self._session.scalars(
                select(ParallelInvocationRequest.id).where(
                    ParallelInvocationRequest.status == "synthesizing",
                    ParallelInvocationRequest.aggregated_message_id.is_(None),
                )
            )
        )

    async def claim_synthesis(
        self, request_id: UUID
    ) -> tuple[ParallelInvocationRequest, list[ParallelInvocationResponse]] | None:
        request = await self._session.scalar(
            select(ParallelInvocationRequest)
            .where(ParallelInvocationRequest.id == request_id)
            .with_for_update()
        )
        if request is None or request.status != "synthesizing":
            return None
        request.status = "synthesis_running"
        request.deadline_at = self._next_deadline()
        responses = list(
            await self._session.scalars(
                select(ParallelInvocationResponse).where(
                    ParallelInvocationResponse.request_id == request_id
                )
            )
        )
        return request, responses

    async def complete_synthesis(self, request_id: UUID, text: str) -> None:
        request = await self._session.scalar(
            select(ParallelInvocationRequest)
            .where(ParallelInvocationRequest.id == request_id)
            .with_for_update()
        )
        if request is None or request.aggregated_message_id is not None:
            return
        responses = list(
            await self._session.scalars(
                select(ParallelInvocationResponse).where(
                    ParallelInvocationResponse.request_id == request_id
                )
            )
        )
        request.status = "done"
        completed_at = datetime.now(UTC)
        request.deadline_at = self._next_deadline(completed_at)
        request.completed_at = completed_at
        await self._aggregate(request, responses, synthesized_text=text)

    async def _aggregate(
        self,
        request: ParallelInvocationRequest,
        responses: list[ParallelInvocationResponse],
        *,
        synthesized_text: str | None = None,
    ) -> None:
        if request.aggregated_message_id is not None:
            return
        by_target = {item.target_agent_id: item for item in responses}
        results: list[dict[str, object]] = []
        lines = ["## 并行协作结果", "", f"**问题**: {request.question}", ""]
        for target in request.targets:
            response = by_target[target]
            text = ""
            if response.content:
                text = str(response.content.get("text", ""))
            results.append(
                {
                    "agent_id": target,
                    "status": response.status,
                    "content": response.content,
                    "error_type": response.error_type,
                }
            )
            lines.extend([f"### {target} — {response.status}", text or "(无回答)", ""])
        message = ConversationMessage(
            conversation_id=request.conversation_id,
            turn_id=request.turn_id,
            reply_to_message_id=request.source_message_id,
            agent_id=request.callback_agent_id,
            role="agent",
            message_type="parallel_result",
            phase="discussion",
            summary=f"并行协作完成: {request.question}"[:1000],
            content={
                "text": synthesized_text or "\n".join(lines),
                "request_id": str(request.id),
                "status": request.status,
                "initiator": request.initiator_agent_id,
                "callback_to": request.callback_agent_id,
                "question": request.question,
                "results": results,
            },
            source_id=f"parallel-result:{request.id}",
        )
        self._session.add(message)
        await self._session.flush()
        request.aggregated_message_id = message.id
        turn = await self._session.get(ConversationTurn, request.turn_id)
        if turn is not None:
            turn.status = request.status
            turn.collaboration_phase = "completed"
            turn.completed_at = request.completed_at or datetime.now(UTC)
