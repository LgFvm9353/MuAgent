from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.task import TaskContract
from app.models import Task
from app.repositories import TaskRepository


class TaskService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = TaskRepository(session)

    async def create(self, contract: TaskContract) -> Task:
        task = Task(
            id=contract.task_id,
            trace_id=uuid4(),
            contract=contract.model_dump(mode="json"),
        )
        await self._repository.add(task)
        await self._session.commit()
        return task

    async def get(self, task_id: UUID) -> Task:
        return await self._repository.get(task_id)

    async def cancel(self, task_id: UUID) -> Task:
        task = await self._repository.request_cancellation(task_id)
        await self._session.commit()
        return task
