from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task
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
            if state in {TaskState.WAITING_CONFIRMATION, TaskState.NEEDS_REVIEW}:
                continue
            if state is TaskState.PENDING:
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
                    if self._has_uncertain_side_effect(task)
                    else "interrupted workflow requires deterministic review after restart"
                ),
            )
            await self._session.commit()
        return tuple(recovered)

    @staticmethod
    def _has_uncertain_side_effect(task: Task) -> bool:
        # Tool calls are loaded by the execution recovery path. A task in EXECUTING
        # is conservatively withheld until its persisted calls have been classified.
        return TaskState(task.state) is TaskState.EXECUTING
