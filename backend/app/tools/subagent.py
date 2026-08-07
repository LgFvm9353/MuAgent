import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent_loop import AgentLoop
from app.contracts.task import RiskLevel
from app.tools.contracts import ToolSource
from app.tools.registry import ToolDefinition, ToolRegistry

SubagentAction = Literal["run", "all", "status", "wait", "steer", "stop"]
ContextMode = Literal["fresh", "fork"]
RunStatus = Literal["queued", "running", "completed", "failed", "stopped"]


class SubagentTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=100)
    agent: str = Field(min_length=1, max_length=100)
    task: str = Field(min_length=1, max_length=50_000)
    context: ContextMode = "fresh"


class SubagentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: SubagentAction = "run"
    agent: str | None = Field(default=None, min_length=1, max_length=100)
    task: str | None = Field(default=None, min_length=1, max_length=50_000)
    context: ContextMode = "fresh"
    tasks: tuple[SubagentTaskInput, ...] = Field(default=(), max_length=16)
    run_id: str | None = None
    message: str | None = Field(default=None, min_length=1, max_length=20_000)
    mode: Literal["steer", "follow_up"] = "steer"
    background: bool = False
    concurrency: int = Field(default=4, ge=1, le=16)

    @model_validator(mode="after")
    def validate_action(self) -> "SubagentInput":
        if self.action == "run" and (self.agent is None or self.task is None):
            raise ValueError("run requires agent and task")
        if self.action == "all":
            if not self.tasks:
                raise ValueError("all requires tasks")
            keys = [item.key for item in self.tasks]
            if len(set(keys)) != len(keys):
                raise ValueError("parallel task keys must be unique")
        if self.action in {"status", "wait", "steer", "stop"} and self.run_id is None:
            raise ValueError(f"{self.action} requires run_id")
        if self.action == "steer" and self.message is None:
            raise ValueError("steer requires message")
        return self


class SubagentOutput(BaseModel):
    action: SubagentAction
    run_id: str | None = None
    status: str
    result: Any | None = None
    runs: tuple[dict[str, Any], ...] = ()
    error: dict[str, str] | None = None


AttachLoop = Callable[[AgentLoop], None]
ChildRunner = Callable[[str, str, ContextMode, AttachLoop], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class _RunRecord:
    id: str
    key: str
    agent: str
    task_text: str
    context: ContextMode
    status: RunStatus = "queued"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    operation: asyncio.Task[dict[str, Any]] | None = None
    loop: AgentLoop | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class SubagentRunManager:
    """Parent-facing run control for independent child AgentLoops."""

    def __init__(self, runner: ChildRunner) -> None:
        self._runner = runner
        self._runs: dict[str, _RunRecord] = {}
        self._groups: dict[str, tuple[str, ...]] = {}

    async def close(self) -> None:
        operations = [
            record.operation
            for record in self._runs.values()
            if record.operation is not None and not record.operation.done()
        ]
        for operation in operations:
            operation.cancel()
        if operations:
            await asyncio.gather(*operations, return_exceptions=True)

    async def execute(self, request: SubagentInput) -> SubagentOutput:
        if request.action == "run":
            assert request.agent is not None and request.task is not None
            record = self._start(
                key="main",
                agent=request.agent,
                task=request.task,
                context=request.context,
            )
            if request.background:
                return SubagentOutput(action="run", run_id=record.id, status=record.status)
            await self._wait(record)
            return self._single_output("run", record)

        if request.action == "all":
            semaphore = asyncio.Semaphore(request.concurrency)
            records = tuple(
                self._start(
                    key=item.key,
                    agent=item.agent,
                    task=item.task,
                    context=item.context,
                    semaphore=semaphore,
                )
                for item in request.tasks
            )
            group_id = str(uuid4())
            self._groups[group_id] = tuple(record.id for record in records)
            if request.background:
                return SubagentOutput(
                    action="all",
                    run_id=group_id,
                    status="running",
                    runs=tuple(self._snapshot(record) for record in records),
                )
            await asyncio.gather(*(self._wait(record) for record in records))
            results = [self._snapshot(record) for record in records]
            failed = any(item["status"] != "completed" for item in results)
            return SubagentOutput(
                action="all",
                run_id=group_id,
                status="failed" if failed else "completed",
                runs=tuple(results),
            )

        assert request.run_id is not None
        if request.run_id in self._groups:
            records = tuple(self._get(run_id) for run_id in self._groups[request.run_id])
            if request.action == "status":
                return SubagentOutput(
                    action="status",
                    run_id=request.run_id,
                    status=self._group_status(records),
                    runs=tuple(self._snapshot(record) for record in records),
                )
            if request.action == "wait":
                await asyncio.gather(*(self._wait(record) for record in records))
                return SubagentOutput(
                    action="wait",
                    run_id=request.run_id,
                    status=self._group_status(records),
                    runs=tuple(self._snapshot(record) for record in records),
                )
            if request.action == "steer":
                assert request.message is not None
                for record in records:
                    if record.loop is not None:
                        if request.mode == "follow_up":
                            await record.loop.follow_up(request.message)
                        else:
                            await record.loop.steer(request.message)
                return SubagentOutput(
                    action="steer",
                    run_id=request.run_id,
                    status=self._group_status(records),
                )
            if request.action == "stop":
                for record in records:
                    self._stop(record)
                return SubagentOutput(action="stop", run_id=request.run_id, status="stopped")
        record = self._get(request.run_id)
        if request.action == "status":
            return self._single_output("status", record)
        if request.action == "wait":
            await self._wait(record)
            return self._single_output("wait", record)
        if request.action == "steer":
            if record.loop is None or request.message is None:
                return SubagentOutput(
                    action="steer",
                    run_id=record.id,
                    status=record.status,
                    error={"code": "subagent_not_running"},
                )
            if request.mode == "follow_up":
                await record.loop.follow_up(request.message)
            else:
                await record.loop.steer(request.message)
            return SubagentOutput(action="steer", run_id=record.id, status=record.status)
        if request.action == "stop":
            self._stop(record)
            return SubagentOutput(action="stop", run_id=record.id, status=record.status)
        raise ValueError(f"unsupported subagent action: {request.action}")

    def _start(
        self,
        *,
        key: str,
        agent: str,
        task: str,
        context: ContextMode,
        semaphore: asyncio.Semaphore | None = None,
    ) -> _RunRecord:
        run_id = str(uuid4())
        record = _RunRecord(run_id, key, agent, task, context)
        self._runs[run_id] = record

        async def operation() -> dict[str, Any]:
            record.status = "running"
            try:
                if semaphore is None:
                    result = await self._runner(
                        agent,
                        task,
                        context,
                        lambda loop: setattr(record, "loop", loop),
                    )
                else:
                    async with semaphore:
                        result = await self._runner(
                            agent,
                            task,
                            context,
                            lambda loop: setattr(record, "loop", loop),
                        )
                record.result = result
                record.status = "completed"
                return result
            except asyncio.CancelledError:
                record.status = "stopped"
                raise
            except Exception as error:
                record.error = type(error).__name__
                record.status = "failed"
                return {"error": {"code": record.error}}
            finally:
                record.completed_at = datetime.now(UTC)

        record.operation = asyncio.create_task(operation(), name=f"subagent:{run_id}")
        return record

    @staticmethod
    async def _wait(record: _RunRecord) -> None:
        if record.operation is None:
            return
        try:
            await record.operation
        except asyncio.CancelledError:
            pass

    def _get(self, run_id: str) -> _RunRecord:
        try:
            return self._runs[run_id]
        except KeyError as error:
            raise ValueError("unknown subagent run") from error

    @staticmethod
    def _group_status(records: tuple[_RunRecord, ...]) -> str:
        statuses = {record.status for record in records}
        if statuses <= {"completed"}:
            return "completed"
        if "running" in statuses or "queued" in statuses:
            return "running"
        if "failed" in statuses:
            return "failed"
        return "stopped"

    @staticmethod
    def _stop(record: _RunRecord) -> None:
        if record.loop is not None:
            record.loop.abort()
        if record.operation is not None and not record.operation.done():
            record.operation.cancel()
        record.status = "stopped"
        record.completed_at = datetime.now(UTC)

    @staticmethod
    def _snapshot(record: _RunRecord) -> dict[str, Any]:
        return {
            "run_id": record.id,
            "key": record.key,
            "agent": record.agent,
            "status": record.status,
            "result": record.result,
            "error": record.error,
        }

    def _single_output(self, action: SubagentAction, record: _RunRecord) -> SubagentOutput:
        return SubagentOutput(
            action=action,
            run_id=record.id,
            status=record.status,
            result=record.result,
            error={"code": record.error} if record.error else None,
        )


def register_subagent_tool(
    registry: ToolRegistry,
    manager: SubagentRunManager,
    *,
    timeout_seconds: float = 1_800.0,
) -> None:
    registry.register(
        ToolDefinition[SubagentInput, SubagentOutput](
            name="subagent",
            description=(
                "Run and control independent child agents. Use action=all for parent-controlled "
                "parallel work with distinct task keys."
            ),
            input_model=SubagentInput,
            output_model=SubagentOutput,
            risk=RiskLevel.LOW,
            timeout_seconds=timeout_seconds,
            idempotent=False,
            max_output_bytes=2_000_000,
            handler=manager.execute,
            source=ToolSource.LOCAL,
            canonical_id="local.subagent",
        )
    )
