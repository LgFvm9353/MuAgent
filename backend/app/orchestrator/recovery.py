from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, ToolCall
from app.orchestrator.state_machine import TaskState
from app.repositories import TaskRepository

ResumeHandler = Callable[[UUID], Awaitable[None]]


class RecoveryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = TaskRepository(session)

    async def recover(self, schedule: ResumeHandler) -> tuple[UUID, ...]:
        recovered: list[UUID] = []
        for task in await self._repository.list_recoverable():
            state = TaskState(task.state)
            if state is TaskState.NEEDS_REVIEW:
                continue
            if state is TaskState.WAITING_CONFIRMATION:
                await self._repository.transition(
                    task.id,
                    TaskState.EXECUTING,
                    expected_version=task.version,
                    trace_id=task.trace_id,
                    reason="legacy confirmation gate removed; resuming through supervisor inbox",
                )
                await self._session.commit()
                await schedule(task.id)
                recovered.append(task.id)
                continue
            if state is TaskState.PENDING:
                await schedule(task.id)
                recovered.append(task.id)
                continue
            if state is TaskState.EXECUTING and not await self._has_uncertain_side_effect(task):
                await schedule(task.id)
                recovered.append(task.id)
                continue
            await self._repository.transition(
                task.id,
                TaskState.NEEDS_REVIEW,
                expected_version=task.version,
                trace_id=task.trace_id,
                reason=(
                    "execution state requires idempotency review after restart"
                    if state is TaskState.EXECUTING
                    else "interrupted workflow requires deterministic review after restart"
                ),
            )
            await self._session.commit()
        return tuple(recovered)

    async def _has_uncertain_side_effect(self, task: Task) -> bool:
        if TaskState(task.state) is not TaskState.EXECUTING:
            return False
        uncertain = await self._session.scalar(
            select(ToolCall.id)
            .where(
                ToolCall.task_id == task.id,
                ToolCall.status.in_(("started", "running", "failed")),
            )
            .limit(1)
        )
        return uncertain is not None
