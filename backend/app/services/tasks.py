from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.task import TaskContract
from app.models import Conversation, Task
from app.orchestrator.state_machine import TERMINAL_STATES, TaskState
from app.repositories import TaskRepository
from app.services.final_summary import FinalSummaryService


class TaskService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = TaskRepository(session)

    async def create(
        self,
        contract: TaskContract,
        *,
        conversation_id: UUID | None = None,
    ) -> Task:
        if conversation_id is None:
            conversation = Conversation(title=contract.goal[:255])
            self._session.add(conversation)
            await self._session.flush()
            conversation_id = conversation.id
        task = Task(
            id=contract.task_id,
            conversation_id=conversation_id,
            trace_id=uuid4(),
            contract=contract.model_dump(mode="json"),
        )
        await self._repository.add(task)
        await self._session.commit()
        return task

    async def get(self, task_id: UUID) -> Task:
        return await self._repository.get(task_id)

    async def list(self, *, limit: int, offset: int) -> list[Task]:
        return await self._repository.list_tasks(limit=limit, offset=offset)

    async def cancel(self, task_id: UUID) -> Task:
        task = await self._repository.request_cancellation(task_id)
        if TaskState(task.state) not in TERMINAL_STATES:
            task = await self._repository.transition(
                task_id,
                TaskState.CANCELLED,
                expected_version=task.version,
                trace_id=task.trace_id,
                reason="user requested cancellation",
            )
            await FinalSummaryService(self._session).add(
                task,
                reason="user requested cancellation",
            )
        await self._session.commit()
        return task
