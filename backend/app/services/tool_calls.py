from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent, Confirmation, EvidenceRecordModel, ToolCall
from app.tools.contracts import ToolInvocation, ToolInvocationResult


class ToolCallConflictError(RuntimeError):
    pass


class ToolCallRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def reserve(
        self,
        invocation: ToolInvocation,
        *,
        idempotency_key: str,
        schema_hash: str | None = None,
        timeout_seconds: float | None = None,
    ) -> ToolCall:
        existing = await self._session.scalar(
            select(ToolCall).where(ToolCall.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing
        call = ToolCall(
            task_id=invocation.context.task_id,
            turn_id=invocation.context.turn_id,
            agent_run_id=invocation.context.agent_run_id,
            tool_name=invocation.tool_name,
            idempotency_key=idempotency_key,
            arguments=invocation.arguments,
            arguments_hash=None,
            schema_hash=schema_hash,
            risk=(invocation.requested_risk.value if invocation.requested_risk else "low"),
            status="requested",
            timeout_seconds=timeout_seconds,
        )
        self._session.add(call)
        try:
            await self._session.flush()
        except IntegrityError as error:
            await self._session.rollback()
            existing = await self._session.scalar(
                select(ToolCall).where(ToolCall.idempotency_key == idempotency_key)
            )
            if existing is None:
                raise ToolCallConflictError("tool call reservation conflicted") from error
            return cast(ToolCall, existing)
        return call

    async def complete(
        self,
        call: ToolCall,
        result: ToolInvocationResult,
        *,
        trace_id: UUID,
    ) -> None:
        call.source = result.source.value
        call.risk = result.risk.value
        call.arguments_hash = result.arguments_digest
        call.status = "completed"
        call.result = result.output.model_dump(mode="json")
        call.completed_at = datetime.now(UTC)
        evidence = EvidenceRecordModel(
            task_id=call.task_id,
            turn_id=call.turn_id,
            agent_run_id=call.agent_run_id,
            tool_call_id=call.id,
            kind="tool_result",
            content={
                "canonical_tool_id": result.canonical_tool_id,
                "duration_ms": result.duration_ms,
                "output": call.result,
            },
        )
        self._session.add(evidence)
        self._session.add(
            AuditEvent(
                task_id=call.task_id,
                turn_id=call.turn_id,
                agent_run_id=call.agent_run_id,
                tool_call_id=call.id,
                trace_id=trace_id,
                event_type="tool_call_completed",
                payload={"canonical_tool_id": result.canonical_tool_id},
            )
        )
        await self._session.flush()

    async def mark_outcome_unknown(self, call: ToolCall, *, error_type: str) -> None:
        call.status = "outcome_unknown"
        call.side_effect_state = "unknown"
        call.error_type = error_type
        call.completed_at = datetime.now(UTC)
        await self._session.flush()

    async def create_confirmation(
        self,
        call: ToolCall,
        *,
        call_hash: str,
        expires_at: datetime,
    ) -> Confirmation:
        confirmation = Confirmation(
            task_id=call.task_id,
            turn_id=call.turn_id,
            tool_call_id=call.id,
            call_hash=call_hash,
            status="pending",
            expires_at=expires_at,
        )
        self._session.add(confirmation)
        await self._session.flush()
        return confirmation

    async def decide_confirmation(
        self,
        confirmation_id: UUID,
        *,
        approved: bool,
        decided_by: str,
    ) -> Confirmation:
        confirmation = await self._session.scalar(
            select(Confirmation).where(Confirmation.id == confirmation_id).with_for_update()
        )
        if confirmation is None:
            raise LookupError(confirmation_id)
        if confirmation.status != "pending":
            if confirmation.approved != approved:
                raise ToolCallConflictError("confirmation decision is immutable")
            return confirmation
        if confirmation.expires_at is not None and confirmation.expires_at <= datetime.now(UTC):
            confirmation.status = "expired"
            raise ToolCallConflictError("confirmation has expired")
        confirmation.status = "approved" if approved else "rejected"
        confirmation.approved = approved
        confirmation.decided_by = decided_by
        await self._session.flush()
        return confirmation
