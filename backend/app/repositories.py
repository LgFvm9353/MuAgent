from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent, EvidenceRecordModel, Task, TaskEvent, UsageRecord
from app.orchestrator.state_machine import TERMINAL_STATES, TaskState, validate_transition


class TaskNotFoundError(LookupError):
    pass


class ConcurrentTaskUpdateError(RuntimeError):
    pass


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, task: Task) -> None:
        self._session.add(task)
        self._session.add(
            TaskEvent(task_id=task.id, event_type="task_created", to_state=task.state, payload={})
        )

    async def get(self, task_id: UUID, *, for_update: bool = False) -> Task:
        statement = select(Task).where(Task.id == task_id)
        if for_update:
            statement = statement.with_for_update()
        task = await self._session.scalar(statement)
        if task is None:
            raise TaskNotFoundError(str(task_id))
        return task

    async def transition(
        self,
        task_id: UUID,
        target: TaskState,
        *,
        expected_version: int,
        trace_id: UUID,
        reason: str,
        details: dict[str, str] | None = None,
    ) -> Task:
        task = await self.get(task_id, for_update=True)
        if task.version != expected_version:
            raise ConcurrentTaskUpdateError(str(task_id))
        current = TaskState(task.state)
        validate_transition(current, target)
        task.state = target.value
        task.version += 1
        task.updated_at = datetime.now(UTC)
        payload = {"reason": reason, "version": task.version, **(details or {})}
        self._session.add(
            TaskEvent(
                task_id=task.id,
                event_type="state_transition",
                from_state=current.value,
                to_state=target.value,
                payload=payload,
            )
        )
        self._session.add(
            AuditEvent(
                task_id=task.id,
                trace_id=trace_id,
                event_type="task.state_transition",
                payload={"from": current.value, "to": target.value, **payload},
            )
        )
        return task

    async def request_cancellation(self, task_id: UUID) -> Task:
        task = await self.get(task_id, for_update=True)
        task.cancel_requested = True
        task.updated_at = datetime.now(UTC)
        return task

    async def list_tasks(self, *, limit: int, offset: int) -> list[Task]:
        result = await self._session.scalars(
            select(Task).order_by(Task.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result)

    async def timeline(self, task_id: UUID) -> list[TaskEvent]:
        await self.get(task_id)
        result = await self._session.scalars(
            select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.id)
        )
        return list(result)

    async def timeline_after(self, task_id: UUID, *, after: int) -> list[TaskEvent]:
        await self.get(task_id)
        result = await self._session.scalars(
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id, TaskEvent.id > after)
            .order_by(TaskEvent.id)
        )
        return list(result)

    async def audit(self, task_id: UUID) -> list[AuditEvent]:
        await self.get(task_id)
        result = await self._session.scalars(
            select(AuditEvent).where(AuditEvent.task_id == task_id).order_by(AuditEvent.id)
        )
        return list(result)

    async def usage(self, task_id: UUID) -> list[UsageRecord]:
        await self.get(task_id)
        result = await self._session.scalars(
            select(UsageRecord)
            .where(UsageRecord.task_id == task_id)
            .order_by(UsageRecord.created_at)
        )
        return list(result)

    async def evidence(self, task_id: UUID) -> list[EvidenceRecordModel]:
        await self.get(task_id)
        result = await self._session.scalars(
            select(EvidenceRecordModel)
            .where(EvidenceRecordModel.task_id == task_id)
            .order_by(EvidenceRecordModel.created_at)
        )
        return list(result)

    async def list_recoverable(self) -> list[Task]:
        terminal = [state.value for state in TERMINAL_STATES]
        result = await self._session.scalars(select(Task).where(Task.state.not_in(terminal)))
        return list(result)
