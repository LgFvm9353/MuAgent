import asyncio
import json
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
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
SupervisorReason = Literal["need_decision", "interview_request", "progress_update"]
OutputMode = Literal["inline", "file-only"]

DEFAULT_MAX_OUTPUT_BYTES = 200 * 1024
DEFAULT_MAX_OUTPUT_LINES = 5_000

_CURRENT_SUPERVISOR_RUN: ContextVar[str | None] = ContextVar(
    "current_supervisor_run", default=None
)
_CURRENT_SUPERVISOR_AGENT: ContextVar[str | None] = ContextVar(
    "current_supervisor_agent", default=None
)
_CURRENT_SUPERVISOR_CONVERSATION: ContextVar[tuple[str, str] | None] = ContextVar(
    "current_supervisor_conversation", default=None
)


def set_supervisor_context(
    run_id: str | None,
    agent: str | None,
    conversation: tuple[str, str] | None,
) -> tuple[object, object, object]:
    return (
        _CURRENT_SUPERVISOR_RUN.set(
            run_id if run_id is not None else _CURRENT_SUPERVISOR_RUN.get()
        ),
        _CURRENT_SUPERVISOR_AGENT.set(
            agent if agent is not None else _CURRENT_SUPERVISOR_AGENT.get()
        ),
        _CURRENT_SUPERVISOR_CONVERSATION.set(
            conversation if conversation is not None else _CURRENT_SUPERVISOR_CONVERSATION.get()
        ),
    )


def reset_supervisor_context(tokens: tuple[object, object, object]) -> None:
    run_token, agent_token, conversation_token = tokens
    _CURRENT_SUPERVISOR_RUN.reset(run_token)  # type: ignore[arg-type]
    _CURRENT_SUPERVISOR_AGENT.reset(agent_token)  # type: ignore[arg-type]
    _CURRENT_SUPERVISOR_CONVERSATION.reset(conversation_token)  # type: ignore[arg-type]


class ContactSupervisorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: SupervisorReason
    message: str = Field(min_length=1, max_length=20_000)
    options: tuple[str, ...] = Field(default=(), max_length=16)


class ContactSupervisorOutput(BaseModel):
    request_id: str
    status: Literal["pending", "replied"]
    reply: str | None = None


class SupervisorControlInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["pending", "reply"]
    request_id: str | None = None
    message: str | None = Field(default=None, min_length=1, max_length=20_000)


class SupervisorControlOutput(BaseModel):
    status: str
    requests: tuple[dict[str, Any], ...] = ()
    request_id: str | None = None
    reply: str | None = None


@dataclass(slots=True)
class SupervisorRequest:
    request_id: str
    run_id: str | None
    agent: str
    reason: SupervisorReason
    message: str
    options: tuple[str, ...]
    conversation_id: str | None
    turn_id: str | None
    status: Literal["pending", "replied"] = "pending"
    reply: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    replied_at: datetime | None = None


class SupervisorInbox:
    """Pi-style parent/supervisor inbox.

    Child agents create a request and block for a reply when the reason is
    blocking. The parent-facing API can list pending requests and reply by id.
    """

    def __init__(self) -> None:
        self._requests: dict[str, SupervisorRequest] = {}
        self._waiters: dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()

    async def contact(self, request: ContactSupervisorInput) -> ContactSupervisorOutput:
        conversation = _CURRENT_SUPERVISOR_CONVERSATION.get()
        item = SupervisorRequest(
            request_id=str(uuid4()),
            run_id=_CURRENT_SUPERVISOR_RUN.get(),
            agent=_CURRENT_SUPERVISOR_AGENT.get() or "agent",
            reason=request.reason,
            message=request.message,
            options=request.options,
            conversation_id=conversation[0] if conversation else None,
            turn_id=conversation[1] if conversation else None,
        )
        async with self._lock:
            self._requests[item.request_id] = item
            waiter = asyncio.Event()
            self._waiters[item.request_id] = waiter
        if request.reason == "progress_update":
            item.status = "replied"
            item.replied_at = datetime.now(UTC)
            self._waiters.pop(item.request_id, None)
            return ContactSupervisorOutput(request_id=item.request_id, status="replied")
        await waiter.wait()
        return ContactSupervisorOutput(
            request_id=item.request_id,
            status="replied",
            reply=item.reply,
        )

    async def pending(self, conversation_id: str | None = None) -> tuple[SupervisorRequest, ...]:
        async with self._lock:
            return tuple(
                item
                for item in self._requests.values()
                if item.status == "pending"
                and (conversation_id is None or item.conversation_id == conversation_id)
            )

    async def reply(self, request_id: str, message: str) -> SupervisorRequest:
        async with self._lock:
            item = self._requests.get(request_id)
            if item is None:
                raise KeyError(request_id)
            if item.status != "pending":
                raise ValueError("supervisor request already answered")
            item.status = "replied"
            item.reply = message
            item.replied_at = datetime.now(UTC)
            waiter = self._waiters.get(request_id)
            if waiter is not None:
                waiter.set()
            return item


def register_supervisor_tool(registry: ToolRegistry, inbox: SupervisorInbox) -> None:
    registry.register(
        ToolDefinition[ContactSupervisorInput, ContactSupervisorOutput](
            name="contact_supervisor",
            description=(
                "Ask the parent supervisor for a decision or structured user input. "
                "need_decision and interview_request pause until a reply arrives; "
                "progress_update is non-blocking."
            ),
            input_model=ContactSupervisorInput,
            output_model=ContactSupervisorOutput,
            risk=RiskLevel.LOW,
            timeout_seconds=86_400,
            idempotent=False,
            max_output_bytes=64_000,
            handler=inbox.contact,
            source=ToolSource.LOCAL,
            canonical_id="local.contact_supervisor",
        )
    )
    registry.register(
        ToolDefinition[SupervisorControlInput, SupervisorControlOutput](
            name="subagent_supervisor",
            description="Inspect pending child-agent requests or reply to one by id.",
            input_model=SupervisorControlInput,
            output_model=SupervisorControlOutput,
            risk=RiskLevel.LOW,
            timeout_seconds=30,
            idempotent=False,
            max_output_bytes=256_000,
            handler=lambda request: supervisor_control(inbox, request),
            source=ToolSource.LOCAL,
            canonical_id="local.subagent_supervisor",
        )
    )


async def supervisor_control(
    inbox: SupervisorInbox,
    request: SupervisorControlInput,
) -> SupervisorControlOutput:
    if request.action == "pending":
        items = await inbox.pending()
        return SupervisorControlOutput(
            status="pending",
            requests=tuple(
                {
                    "request_id": item.request_id,
                    "agent": item.agent,
                    "reason": item.reason,
                    "message": item.message,
                    "options": item.options,
                    "run_id": item.run_id,
                }
                for item in items
            ),
        )
    if request.request_id is None or request.message is None:
        return SupervisorControlOutput(status="error")
    item = await inbox.reply(request.request_id, request.message)
    return SupervisorControlOutput(status="replied", request_id=item.request_id, reply=item.reply)


class MaxOutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bytes: int = Field(default=DEFAULT_MAX_OUTPUT_BYTES, ge=1)
    lines: int = Field(default=DEFAULT_MAX_OUTPUT_LINES, ge=1)


class SubagentTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=100)
    agent: str = Field(min_length=1, max_length=100)
    task: str = Field(min_length=1, max_length=50_000)
    context: ContextMode = "fresh"
    max_output: MaxOutputConfig = Field(default_factory=MaxOutputConfig)
    output: str | None = Field(default=None, min_length=1, max_length=500)
    output_mode: OutputMode = "inline"
    artifacts: bool = True
    include_progress: bool = False


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
    max_output: MaxOutputConfig = Field(default_factory=MaxOutputConfig)
    output: str | None = Field(default=None, min_length=1, max_length=500)
    output_mode: OutputMode = "inline"
    artifacts: bool = True
    include_progress: bool = False

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
    output_file: str | None = None
    truncated: bool = False


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
    max_output: MaxOutputConfig = field(default_factory=MaxOutputConfig)
    output: str | None = None
    output_mode: OutputMode = "inline"
    artifacts: bool = True
    include_progress: bool = False
    output_file: str | None = None
    truncated: bool = False


def _format_bytes(value: int) -> str:
    if value < 1024:
        return f"{value}B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f}KB"
    return f"{value / (1024 * 1024):.1f}MB"


def _truncate_output(
    output: str,
    max_bytes: int,
    max_lines: int,
    artifact_path: str | None = None,
) -> tuple[str, bool]:
    """Port pi-subagents' first-lines/byte bounded final-output behavior."""
    lines = output.split("\n")
    byte_count = len(output.encode("utf-8"))
    if byte_count <= max_bytes and len(lines) <= max_lines:
        return output, False
    kept = lines[:max_lines]
    result = "\n".join(kept)
    if len(result.encode("utf-8")) > max_bytes:
        low = 0
        high = len(result)
        while low < high:
            middle = (low + high + 1) // 2
            if len(result[:middle].encode("utf-8")) <= max_bytes:
                low = middle
            else:
                high = middle - 1
        result = result[:low]
    kept_lines = len(result.split("\n"))
    marker = (
        f"[TRUNCATED: showing first {kept_lines} of {len(lines)} lines, "
        f"{_format_bytes(len(result.encode('utf-8')))} of {_format_bytes(byte_count)}"
        f"{f' - full output at {artifact_path}' if artifact_path else ''}]\n"
    )
    return marker + result, True


class SubagentRunManager:
    """Parent-facing run control for independent child AgentLoops."""

    def __init__(
        self,
        runner: ChildRunner,
        *,
        supervisor_inbox: SupervisorInbox | None = None,
        artifact_root: Path | None = None,
    ) -> None:
        self._runner = runner
        self._supervisor_inbox = supervisor_inbox
        self._runs: dict[str, _RunRecord] = {}
        self._groups: dict[str, tuple[str, ...]] = {}
        self._artifact_root = artifact_root.resolve() if artifact_root is not None else None

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
                max_output=request.max_output,
                output=request.output,
                output_mode=request.output_mode,
                artifacts=request.artifacts,
                include_progress=request.include_progress,
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
                    max_output=item.max_output,
                    output=item.output,
                    output_mode=item.output_mode,
                    artifacts=item.artifacts,
                    include_progress=item.include_progress,
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
        max_output: MaxOutputConfig | None = None,
        output: str | None = None,
        output_mode: OutputMode = "inline",
        artifacts: bool = True,
        include_progress: bool = False,
    ) -> _RunRecord:
        run_id = str(uuid4())
        record = _RunRecord(
            run_id,
            key,
            agent,
            task,
            context,
            max_output=max_output or MaxOutputConfig(),
            output=output,
            output_mode=output_mode,
            artifacts=artifacts,
            include_progress=include_progress,
        )
        self._runs[run_id] = record

        async def operation() -> dict[str, Any]:
            record.status = "running"
            context_tokens = set_supervisor_context(
                record.id,
                record.agent,
                _CURRENT_SUPERVISOR_CONVERSATION.get(),
            )
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
                record.result = self._capture_result(record, result)
                record.status = "completed"
                return record.result
            except asyncio.CancelledError:
                record.status = "stopped"
                raise
            except Exception as error:
                record.error = type(error).__name__
                record.status = "failed"
                return {"error": {"code": record.error}}
            finally:
                reset_supervisor_context(context_tokens)
                record.completed_at = datetime.now(UTC)

        record.operation = asyncio.create_task(operation(), name=f"subagent:{run_id}")
        return record

    def _capture_result(self, record: _RunRecord, result: dict[str, Any]) -> dict[str, Any]:
        """Apply pi-subagents' bounded final-output and file-only semantics."""
        projected = dict(result)
        text = result.get("text")
        output_text = (
            text
            if isinstance(text, str)
            else json.dumps(result, ensure_ascii=False, default=str)
        )
        artifact_dir = self._artifact_root / record.id if self._artifact_root is not None else None
        output_path: Path | None = None
        if record.output_mode == "file-only" or record.output is not None or record.artifacts:
            if artifact_dir is not None:
                artifact_dir.mkdir(parents=True, exist_ok=True)
                if record.output is not None:
                    requested = Path(record.output)
                    output_path = requested if requested.is_absolute() else artifact_dir / requested
                else:
                    output_path = artifact_dir / f"{record.agent}-output.md"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(output_text, encoding="utf-8")
                record.output_file = str(output_path)
                (artifact_dir / f"{record.agent}-result.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
                worktree = projected.get("worktree")
                if (
                    isinstance(worktree, dict)
                    and isinstance(worktree.get("patch"), str)
                    and worktree["patch"]
                ):
                    patch_path = artifact_dir / f"{record.agent}-patch.diff"
                    patch_path.write_text(worktree["patch"], encoding="utf-8")
                    projected["worktree"] = {
                        **worktree,
                        "patch": "",
                        "patch_path": str(patch_path),
                    }
        if isinstance(text, str):
            truncated = _truncate_output(
                text,
                record.max_output.bytes,
                record.max_output.lines,
                record.output_file,
            )
            record.truncated = truncated[1]
            if record.output_mode == "file-only" and output_path is not None:
                projected["text"] = f"Output saved to: {output_path}"
            else:
                projected["text"] = truncated[0]
            if record.output_mode == "file-only":
                projected["output_file"] = record.output_file
                projected["truncated"] = record.truncated
        return projected

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
            "output_file": record.output_file,
            "truncated": record.truncated,
        }

    def _single_output(self, action: SubagentAction, record: _RunRecord) -> SubagentOutput:
        return SubagentOutput(
            action=action,
            run_id=record.id,
            status=record.status,
            result=record.result,
            error={"code": record.error} if record.error else None,
            output_file=record.output_file,
            truncated=record.truncated,
        )


def register_subagent_tool(
    registry: ToolRegistry,
    manager: SubagentRunManager,
    *,
    timeout_seconds: float = 86_400.0,
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
