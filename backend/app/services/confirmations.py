from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.execution import ExecutionPlan
from app.contracts.task import RiskLevel
from app.models import Confirmation, ExecutionPlanRecord, Task
from app.orchestrator.state_machine import TaskState
from app.repositories import TaskRepository
from app.tools.policy import call_hash as plan_call_hash


class ConfirmationConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PendingConfirmation:
    plan_id: UUID
    plan_version: int
    step_id: str
    tool_name: str
    arguments: dict[str, Any]
    impact: str
    risk: str
    call_hash: str


class ConfirmationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def pending(self, task_id: UUID) -> tuple[PendingConfirmation, ...]:
        task = await self._session.get(Task, task_id)
        if task is None or task.state != TaskState.WAITING_CONFIRMATION.value:
            return ()
        plan_record = await self._session.scalar(
            select(ExecutionPlanRecord)
            .where(ExecutionPlanRecord.task_id == task_id)
            .order_by(ExecutionPlanRecord.version.desc())
            .limit(1)
        )
        if plan_record is None:
            raise ConfirmationConflictError("waiting task has no execution plan")
        plan = ExecutionPlan.model_validate(plan_record.content)
        decided_hashes = set(
            await self._session.scalars(
                select(Confirmation.call_hash).where(
                    Confirmation.task_id == task_id,
                    Confirmation.plan_id == plan.plan_id,
                )
            )
        )
        return tuple(
            PendingConfirmation(
                plan_id=plan.plan_id,
                plan_version=plan.version,
                step_id=step.step_id,
                tool_name=step.tool_name,
                arguments=step.arguments,
                impact=step.expected_result,
                risk=step.risk.value,
                call_hash=plan_call_hash(plan, step),
            )
            for step in plan.steps
            if step.risk is RiskLevel.HIGH and plan_call_hash(plan, step) not in decided_hashes
        )

    async def decide(
        self,
        *,
        task_id: UUID,
        plan_id: UUID,
        plan_version: int,
        call_hash: str,
        approved: bool,
        decided_by: str,
    ) -> Confirmation:
        task = await self._session.scalar(select(Task).where(Task.id == task_id).with_for_update())
        plan = await self._session.scalar(
            select(ExecutionPlanRecord).where(
                ExecutionPlanRecord.id == plan_id,
                ExecutionPlanRecord.task_id == task_id,
                ExecutionPlanRecord.version == plan_version,
            )
        )
        if task is None or plan is None or task.state != TaskState.WAITING_CONFIRMATION.value:
            raise ConfirmationConflictError("task is not waiting for this plan confirmation")
        execution_plan = ExecutionPlan.model_validate(plan.content)
        required_hashes = {
            plan_call_hash(execution_plan, step)
            for step in execution_plan.steps
            if step.risk is RiskLevel.HIGH
        }
        if call_hash not in required_hashes:
            raise ConfirmationConflictError("call hash is not required by the current plan")
        existing = await self._session.scalar(
            select(Confirmation).where(
                Confirmation.task_id == task_id,
                Confirmation.plan_id == plan_id,
                Confirmation.call_hash == call_hash,
            )
        )
        if existing is not None:
            if existing.approved != approved:
                raise ConfirmationConflictError("confirmation decision is immutable")
            return existing
        confirmation = Confirmation(
            task_id=task_id,
            plan_id=plan_id,
            call_hash=call_hash,
            approved=approved,
            decided_by=decided_by,
        )
        self._session.add(confirmation)
        await self._session.flush()
        repository = TaskRepository(self._session)
        if not approved:
            await repository.transition(
                task_id,
                TaskState.REJECTED,
                expected_version=task.version,
                trace_id=task.trace_id,
                reason="user rejected high-risk operation",
            )
        else:
            approved_hashes = set(
                await self._session.scalars(
                    select(Confirmation.call_hash).where(
                        Confirmation.task_id == task_id,
                        Confirmation.plan_id == plan_id,
                        Confirmation.approved.is_(True),
                    )
                )
            )
            if required_hashes <= approved_hashes:
                await repository.transition(
                    task_id,
                    TaskState.EXECUTING,
                    expected_version=task.version,
                    trace_id=task.trace_id,
                    reason="all high-risk operations approved",
                )
        await self._session.commit()
        return confirmation
