import asyncio
from pathlib import Path
from uuid import UUID

import anthropic
import httpx
import openai
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.agents.definitions import build_agent_registry
from app.agents.runtime import AgentRuntime, StructuredGateway
from app.config import Settings
from app.contracts.task import TaskContract
from app.errors import safe_error_summary
from app.harness.model_gateway import ModelGateway
from app.harness.openai_gateway import OpenAIModelGateway
from app.logging import logger
from app.models import ConversationMessage
from app.orchestrator.execution import ExecutionService
from app.orchestrator.service import OrchestratorService
from app.orchestrator.state_machine import TaskState
from app.repositories import TaskNotFoundError, TaskRepository
from app.services.conversation import ConversationService
from app.tools.executor import ToolExecutor
from app.tools.factory import build_tool_registry
from app.workspace.task_directory import (
    WorkspacePreconditionError,
    ensure_task_directory,
)


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
        self._client: openai.AsyncOpenAI | anthropic.AsyncAnthropic
        self._gateway: StructuredGateway
        if settings.llm_provider == "openai":
            self._client = openai.AsyncOpenAI(
                api_key=settings.openai_api_key.get_secret_value()
                if settings.openai_api_key
                else None,
                base_url=settings.openai_base_url,
                max_retries=0,
                timeout=settings.model_timeout_seconds,
                http_client=httpx.AsyncClient(trust_env=False),
            )
            self._gateway = OpenAIModelGateway(
                self._client,
                concurrency=settings.model_concurrency,
                timeout_seconds=settings.model_timeout_seconds,
            )
        else:
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
        try:
            contract = await self._contract(task_id)
            workspace_root = ensure_task_directory(self._settings.workspace_root, task_id)
            workspace_files = frozenset(
                path.relative_to(workspace_root).as_posix()
                for path in workspace_root.rglob("*")
                if path.is_file() and not path.is_symlink()
            )
            tools = build_tool_registry(self._settings, workspace_root)
            runtime = AgentRuntime(
                self._gateway,
                self._agents,
                tools,
                ConversationService(self._sessions).sink(task_id),
            )
            orchestrator = OrchestratorService(self._sessions, runtime, self._agents, tools)
            executor = ExecutionService(
                self._sessions,
                runtime,
                self._agents,
                ToolExecutor(tools),
                workspace_root,
            )
            state = await self._state(task_id)
            max_transitions = 3 + 2 * contract.budget.max_revisions
            transitions = 0
            while state in {TaskState.PENDING, TaskState.EXECUTING, TaskState.REPLANNING}:
                previous = state
                if state is TaskState.PENDING:
                    await orchestrator.run(task_id, workspace_files)
                elif state is TaskState.EXECUTING:
                    await executor.execute(task_id)
                else:
                    workspace_files = frozenset(
                        path.relative_to(workspace_root).as_posix()
                        for path in workspace_root.rglob("*")
                        if path.is_file() and not path.is_symlink()
                    )
                    await orchestrator.replan(task_id, workspace_files)
                state = await self._state(task_id)
                transitions += 1
                if state is previous:
                    raise RuntimeError(f"orchestrator made no state progress: {state}")
                if transitions > max_transitions:
                    raise RuntimeError("orchestrator exceeded the bounded state loop")
        except WorkspacePreconditionError as error:
            error_code, message = safe_error_summary(error)
            logger().warning("task needs workspace review", error_code=error_code)
            await self._finish(
                task_id,
                TaskState.NEEDS_REVIEW,
                error_code,
                details={"error_code": error_code, "message": message},
            )
        except asyncio.CancelledError:
            await self._finish(task_id, TaskState.CANCELLED, "background operation cancelled")
            raise
        except Exception as error:
            error_code, message = safe_error_summary(error)
            logger().exception(
                "task orchestration failed",
                error_code=error_code,
                error_message=message,
            )
            await self._finish(
                task_id,
                TaskState.FAILED,
                error_code,
                details={"error_code": error_code, "message": message},
            )
        finally:
            clear_contextvars()

    async def _contract(self, task_id: UUID) -> TaskContract:
        async with self._sessions() as session:
            task = await TaskRepository(session).get(task_id)
            return TaskContract.model_validate(task.contract)

    async def _trace_id(self, task_id: UUID) -> UUID:
        async with self._sessions() as session:
            task = await TaskRepository(session).get(task_id)
            return task.trace_id

    async def _state(self, task_id: UUID) -> TaskState:
        async with self._sessions() as session:
            task = await TaskRepository(session).get(task_id)
            return TaskState(task.state)

    async def _finish(
        self,
        task_id: UUID,
        target: TaskState,
        reason: str,
        *,
        details: dict[str, str] | None = None,
    ) -> None:
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
                    details=details,
                )
            except ValueError:
                await session.rollback()
                return
            if target in {
                TaskState.NEEDS_REVIEW,
                TaskState.FAILED,
                TaskState.REJECTED,
                TaskState.BUDGET_EXCEEDED,
            }:
                message = (details or {}).get("message", reason)
                session.add(
                    ConversationMessage(
                        task_id=task_id,
                        agent_id="system",
                        role="system",
                        message_type="terminal_result",
                        phase="completion",
                        summary=message[:1000],
                        content={
                            "state": target.value,
                            "reason": reason,
                            "details": details or {},
                            "action": "请根据错误详情调整任务输入后重试。",
                        },
                        source_id=f"terminal-result:{target.value}:{task.version + 1}",
                    )
                )
            await session.commit()
