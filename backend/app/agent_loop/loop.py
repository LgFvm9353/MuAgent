import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .messages import AgentMessage, ToolCall, ToolResult
from .providers import ModelTurnProvider


class ToolExecutor(Protocol):
    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class AgentLoopError(RuntimeError):
    pass


class AgentAbortedError(AgentLoopError):
    pass


@dataclass(frozen=True, slots=True)
class AgentLoopConfig:
    parallel_tools: bool = True
    max_tokens: int = 64_000
    effort: str = "high"


@dataclass(frozen=True, slots=True)
class AgentLoopEvent:
    type: str
    turn: int
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentLoopResult:
    content: Any
    transcript: tuple[AgentMessage, ...]
    usage: Any | None
    turns: int
    tool_calls: int


EventSink = Callable[[AgentLoopEvent], Awaitable[None] | None]


class AgentLoop:
    """A reusable, provider-neutral, model-driven multi-turn loop.

    The loop is deliberately unaware of MCP, skills, or subagents. They are
    exposed as ordinary tools through ``ToolExecutor`` and ``tools``.
    """

    def __init__(
        self,
        *,
        provider: ModelTurnProvider,
        model: str,
        system: str,
        tools: tuple[dict[str, Any], ...] = (),
        executor: ToolExecutor | None = None,
        config: AgentLoopConfig | None = None,
        events: EventSink | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.system = system
        self.tools = tools
        self.executor = executor
        self.config = config or AgentLoopConfig()
        self.events = events
        self.transcript: list[AgentMessage] = []
        self._messages: list[dict[str, Any]] = []
        self._steering: asyncio.Queue[str] = asyncio.Queue()
        self._followups: asyncio.Queue[str] = asyncio.Queue()
        self._abort = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._task: asyncio.Task[AgentLoopResult] | None = None

    async def prompt(self, content: str) -> AgentLoopResult:
        """Start a run with a new user message (or wait for an active run)."""
        if self._task is not None and not self._task.done():
            await self.follow_up(content)
            return await self._task
        self._abort.clear()
        self._idle.clear()
        self._task = asyncio.create_task(self._run(content))
        try:
            await self._emit(AgentLoopEvent("agent_start", 0))
            return await self._task
        except asyncio.CancelledError as error:
            raise AgentAbortedError("agent_aborted") from error
        finally:
            await self._emit(AgentLoopEvent("agent_end", 0))
            self._idle.set()

    async def continue_run(self, content: str | None = None) -> AgentLoopResult:
        """Continue an existing transcript without resetting it."""
        if self._task is not None and not self._task.done():
            return await self._task
        self._abort.clear()
        self._idle.clear()
        if content:
            self._messages.append({"role": "user", "content": content})
            self.transcript.append(AgentMessage("user", content))
        try:
            return await self._run(None)
        finally:
            self._idle.set()

    async def continue_(self, content: str | None = None) -> AgentLoopResult:
        """Python-friendly spelling of pi's ``continue()`` API."""
        return await self.continue_run(content)

    async def steer(self, content: str) -> None:
        await self._steering.put(content)

    async def follow_up(self, content: str) -> None:
        await self._followups.put(content)

    def abort(self) -> None:
        self._abort.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()

    async def wait_for_idle(self) -> None:
        await self._idle.wait()

    def inherit_context(self, parent: "AgentLoop") -> None:
        """Seed a child with a safe snapshot of the parent's conversation.

        Parent tool-call messages are orchestration implementation details, not
        child instructions.  Keeping them in a fork both wastes context and
        lets a child accidentally replay the parent's tool protocol.  Retain
        ordinary user/assistant text, while dropping assistant messages that
        contain tool calls and all tool result messages.
        """
        if self._task is not None and not self._task.done():
            raise AgentLoopError("cannot_inherit_context_while_running")
        self._messages = [
            dict(message)
            for message in parent._messages
            if message.get("role") != "tool" and not message.get("tool_calls")
        ]
        self.transcript = [
            message
            for message in parent.transcript
            if message.role != "tool" and not message.metadata.get("tool_call_id")
        ]

    async def _emit(self, event: AgentLoopEvent) -> None:
        if self.events is None:
            return
        result = self.events(event)
        if asyncio.iscoroutine(result):
            await result

    async def _run(self, content: str | None) -> AgentLoopResult:
        if content is not None:
            self._messages.append({"role": "user", "content": content})
            self.transcript.append(AgentMessage("user", content))
        usage: Any | None = None
        tool_count = 0
        last_content: Any = None
        turn = 0
        while True:
            turn += 1
            if self._abort.is_set():
                raise AgentAbortedError("agent_aborted")
            while not self._steering.empty():
                steering = await self._steering.get()
                self._messages.append({"role": "user", "content": steering})
                self.transcript.append(AgentMessage("user", steering, {"steering": True}))
            await self._emit(AgentLoopEvent("turn_start", turn))

            async def on_text_delta(delta: str, current_turn: int = turn) -> None:
                await self._emit(AgentLoopEvent("text_delta", current_turn, {"text": delta}))

            model_turn = await self.provider.turn(
                model=self.model,
                system=self.system,
                messages=list(self._messages),
                tools=self.tools,
                max_tokens=self.config.max_tokens,
                effort=self.config.effort,
                on_text_delta=on_text_delta if self.events is not None else None,
            )
            usage = _merge_usage(usage, model_turn.usage)
            last_content = model_turn.content
            self._messages.append(model_turn.assistant_message)
            self.transcript.append(AgentMessage("assistant", model_turn.content))
            await self._emit(
                AgentLoopEvent(
                    "message_end",
                    turn,
                    {
                        "stop_reason": model_turn.stop_reason,
                        "tool_calls": len(model_turn.tool_calls),
                    },
                )
            )
            if model_turn.stop_reason in {"stop", "end_turn"} and not model_turn.tool_calls:
                if not self._followups.empty():
                    followup = await self._followups.get()
                    self._messages.append({"role": "user", "content": followup})
                    self.transcript.append(AgentMessage("user", followup, {"follow_up": True}))
                    continue
                return AgentLoopResult(
                    last_content, tuple(self.transcript), usage, turn, tool_count
                )
            if model_turn.stop_reason == "pause_turn":
                self._messages.append(
                    {"role": "user", "content": "Continue the previous response."}
                )
                self.transcript.append(AgentMessage("user", "Continue the previous response."))
                continue
            if not model_turn.tool_calls:
                raise AgentLoopError("tool_use_without_tool_calls")
            if self.executor is None:
                raise AgentLoopError("tool_executor_not_configured")
            tool_count += len(model_turn.tool_calls)
            results = tuple(await self._execute_tools(model_turn.tool_calls, turn))
            self._messages.extend(self.provider.tool_result_messages(results))
            for result in results:
                self.transcript.append(
                    AgentMessage(
                        "tool",
                        result.content,
                        {
                            "tool_call_id": result.call_id,
                            "name": result.name,
                            "is_error": result.is_error,
                        },
                    )
                )

    async def _execute_tools(self, calls: tuple[ToolCall, ...], turn: int) -> list[ToolResult]:
        executor = self.executor
        if executor is None:
            raise AgentLoopError("tool_executor_not_configured")

        async def invoke(call: ToolCall) -> ToolResult:
            await self._emit(
                AgentLoopEvent("tool_execution_start", turn, {"id": call.id, "name": call.name})
            )
            if call.error_code is not None:
                result = ToolResult(
                    call.id,
                    call.name,
                    {"error": {"code": call.error_code}},
                    True,
                )
                await self._emit(
                    AgentLoopEvent(
                        "tool_execution_end",
                        turn,
                        {"id": call.id, "name": call.name, "is_error": True},
                    )
                )
                return result
            if call.arguments is None:
                result = ToolResult(
                    call.id, call.name, {"error": {"code": "tool_input_invalid"}}, True
                )
                await self._emit(
                    AgentLoopEvent(
                        "tool_execution_end",
                        turn,
                        {"id": call.id, "name": call.name, "is_error": True},
                    )
                )
                return result
            try:
                output = await executor.execute(call.name, call.arguments)
                return ToolResult(
                    call.id,
                    call.name,
                    output,
                    "error" in output,
                )
            except Exception as error:
                return ToolResult(
                    call.id,
                    call.name,
                    {"error": {"code": type(error).__name__}},
                    True,
                )
            finally:
                await self._emit(
                    AgentLoopEvent(
                        "tool_execution_end",
                        turn,
                        {"id": call.id, "name": call.name},
                    )
                )

        if self.config.parallel_tools:
            return await asyncio.gather(*(invoke(call) for call in calls))
        return [await invoke(call) for call in calls]


def _merge_usage(current: Any | None, incoming: Any) -> Any:
    if current is None:
        return incoming
    return type(incoming)(
        request_id=incoming.request_id,
        model=incoming.model,
        stop_reason=incoming.stop_reason,
        input_tokens=current.input_tokens + incoming.input_tokens,
        output_tokens=current.output_tokens + incoming.output_tokens,
        cache_creation_input_tokens=current.cache_creation_input_tokens
        + incoming.cache_creation_input_tokens,
        cache_read_input_tokens=current.cache_read_input_tokens + incoming.cache_read_input_tokens,
        latency_ms=current.latency_ms + incoming.latency_ms,
        retry_count=current.retry_count + incoming.retry_count,
    )
