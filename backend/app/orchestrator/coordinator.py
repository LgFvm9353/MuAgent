import asyncio
from pathlib import Path
from uuid import UUID

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.agents.definitions import build_agent_registry
from app.agents.runtime import ClaudeAgentRuntime
from app.config import Settings
from app.harness.model_gateway import ModelGateway
from app.orchestrator.execution import ExecutionService
from app.orchestrator.service import OrchestratorService
from app.orchestrator.state_machine import TaskState
from app.repositories import TaskNotFoundError, TaskRepository
from app.tools.executor import ToolExecutor
from app.tools.factory import build_tool_registry


class Coordinator:
    def __init__(
        self,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        prompts_root: Path,
    ) -> None:
        self._settings = settings
        self._sessions = sessions
        self._prompts_root = prompts_root
        self._active: dict[UUID, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
            if settings.anthropic_api_key
            else None,
            max_retries=0,
            timeout=settings.model_timeout_seconds,
        )
        self._gateway = ModelGateway(
            self._client,
            concurrency=settings.model_concurrency,
            timeout_seconds=settings.model_timeout_seconds,
        )
        self._agents = build_agent_registry(settings, prompts_root)

    async def schedule(self, task_id: UUID) -> None:
        async with self._lock:
            current = self._active.get(task_id)
            if current is not None and not current.done():
                return
            operation = asyncio.create_task(self._run(task_id), name=f"task:{task_id}")
            self._active[task_id] = operation

            def remove(finished: asyncio.Task[None]) -> None:
                if self._active.get(task_id) is finished:
                    self._active.pop(task_id, None)

            operation.add_done_callback(remove)

    async def cancel(self, task_id: UUID) -> None:
        async with self._lock:
            operation = self._active.get(task_id)
            if operation is not None and not operation.done():
                operation.cancel()

    async def close(self) -> None:
        async with self._lock:
            operations = tuple(self._active.values())
            for operation in operations:
                operation.cancel()
        if operations:
            await asyncio.gather(*operations, return_exceptions=True)
        await self._client.close()

    async def _run(self, task_id: UUID) -> None:
        trace_id = await self._trace_id(task_id)
        clear_contextvars()
        bind_contextvars(task_id=str(task_id), trace_id=str(trace_id))
        tools = build_tool_registry(self._settings, str(task_id))
        runtime = ClaudeAgentRuntime(self._gateway, self._agents, tools)
        try:
            state = await self._state(task_id)
            orchestrator = OrchestratorService(self._sessions, runtime, self._agents, tools)
            if state is TaskState.PENDING:
                await orchestrator.run(task_id)
                state = await self._state(task_id)
            if state is TaskState.EXECUTING:
                await ExecutionService(
                    self._sessions,
                    runtime,
                    self._agents,
                    ToolExecutor(tools),
                ).execute(task_id)
                state = await self._state(task_id)
            if state is TaskState.REPLANNING:
                await orchestrator.replan(task_id)
                state = await self._state(task_id)
                if state is TaskState.EXECUTING:
                    await ExecutionService(
                        self._sessions,
                        runtime,
                        self._agents,
                        ToolExecutor(tools),
                    ).execute(task_id)
        except asyncio.CancelledError:
            await self._finish(task_id, TaskState.CANCELLED, "background operation cancelled")
            raise
        except Exception as error:
            await self._finish(task_id, TaskState.FAILED, type(error).__name__)
        finally:
            clear_contextvars()

    async def _trace_id(self, task_id: UUID) -> UUID:
        async with self._sessions() as session:
            task = await TaskRepository(session).get(task_id)
            return task.trace_id

    async def _state(self, task_id: UUID) -> TaskState:
        async with self._sessions() as session:
            task = await TaskRepository(session).get(task_id)
            return TaskState(task.state)

    async def _finish(self, task_id: UUID, target: TaskState, reason: str) -> None:
        async with self._sessions() as session:
            repository = TaskRepository(session)
            try:
                task = await repository.get(task_id, for_update=True)
            except TaskNotFoundError:
                return
            current = TaskState(task.state)
            if current in {
                TaskState.SUCCEEDED,
                TaskState.FAILED,
                TaskState.CANCELLED,
                TaskState.REJECTED,
                TaskState.BUDGET_EXCEEDED,
            }:
                return
            try:
                await repository.transition(
                    task_id,
                    target,
                    expected_version=task.version,
                    trace_id=task.trace_id,
                    reason=reason,
                )
            except ValueError:
                await session.rollback()
                return
            await session.commit()
