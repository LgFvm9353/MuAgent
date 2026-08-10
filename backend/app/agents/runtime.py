import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from pydantic import BaseModel

from app.agent_loop import AgentLoop, AgentLoopConfig, ModelTurnProvider
from app.contracts.agents import VerificationReport
from app.contracts.execution import ExecutionPlan
from app.contracts.task import TaskContract
from app.harness.context import ContextBuilder
from app.harness.model_gateway import ModelUsage
from app.harness.registry import AgentRegistry
from app.harness.structured_tools import (
    anthropic_text,
    parse_structured_output,
    structured_output_system,
)
from app.tools.agent_binding import bind_agent_tools
from app.tools.contracts import ToolContext
from app.tools.registry import ToolRegistry


@dataclass(frozen=True, slots=True)
class AgentInvocation:
    """Persistable record of one structured model invocation."""

    agent_id: str
    output: dict[str, Any]
    usage: ModelUsage
    source_id: str
    phase: str
    message_type: str


CollaborationSink = Callable[[AgentInvocation], Awaitable[None]]


class StructuredGateway(Protocol):
    def model_turn_provider(self) -> ModelTurnProvider: ...


class AgentRuntime:
    def __init__(
        self,
        gateway: StructuredGateway,
        agents: AgentRegistry,
        tools: ToolRegistry,
        message_sink: Callable[[AgentInvocation], Awaitable[None]] | None = None,
    ) -> None:
        self._gateway = gateway
        self._agents = agents
        self._tools = tools
        self._message_sink = message_sink
        self._context = ContextBuilder()
        self._invocations: list[AgentInvocation] = []

    def drain_invocations(self) -> tuple[AgentInvocation, ...]:
        invocations = tuple(self._invocations)
        self._invocations.clear()
        return invocations

    async def supervisor_plan(
        self,
        task: TaskContract,
        workspace_files: frozenset[str] = frozenset(),
    ) -> ExecutionPlan:
        """Ask the root Supervisor for a plan.

        The Supervisor may delegate specialist work through ``subagent``.
        """
        context = self._context.decomposition(
            task,
            self._tools.catalog(task.allowed_tools),
            workspace_files,
            self._available_agents(),
        )
        return cast(
            ExecutionPlan,
            await self._call_supervisor(
                "decomposition",
                context,
                ExecutionPlan,
                task_id=task.task_id,
            ),
        )

    async def supervisor_replan(
        self,
        task: TaskContract,
        prior_plan: ExecutionPlan,
        verification: VerificationReport,
        evidence: tuple[dict[str, Any], ...],
        workspace_files: frozenset[str],
    ) -> ExecutionPlan:
        """Ask the root Supervisor to revise a plan after verified failures."""
        context = self._context.replanning(
            task,
            prior_plan.model_dump(mode="json"),
            verification.model_dump(mode="json"),
            evidence,
            self._tools.catalog(task.allowed_tools),
            workspace_files,
            self._available_agents(),
        )
        return cast(
            ExecutionPlan,
            await self._call_supervisor(
                "replanning",
                context,
                ExecutionPlan,
                task_id=task.task_id,
            ),
        )

    def _available_agents(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "id": definition.agent_id,
                "description": definition.description,
                "capabilities": sorted(definition.capabilities),
            }
            for definition in self._agents.all()
            if definition.agent_id != "supervisor"
        )

    async def supervisor_verify(
        self,
        task: TaskContract,
        plan: ExecutionPlan,
        execution: tuple[dict[str, Any], ...],
        evidence: tuple[dict[str, Any], ...],
        artifacts: tuple[dict[str, Any], ...],
    ) -> VerificationReport:
        """Ask the root Supervisor to synthesize verification.

        An independent reviewer remains optional and is requested by the
        Supervisor through ``subagent`` when needed. Deterministic evidence is
        still collected by the execution layer before this call.
        """
        context = self._context.verification(
            task,
            plan.model_dump(mode="json"),
            execution,
            evidence,
            artifacts,
        )
        return cast(
            VerificationReport,
            await self._call_supervisor(
                "verification",
                context,
                VerificationReport,
                task_id=task.task_id,
            ),
        )

    async def _call_supervisor(
        self,
        phase: str,
        context: dict[str, Any],
        output_model: type[BaseModel],
        *,
        task_id: UUID,
    ) -> BaseModel:
        """Run the root Supervisor with its tool-bound AgentLoop.

        Unlike the legacy structured calls, this path exposes ``subagent`` to
        the model, so every specialist invocation is initiated by Supervisor.
        """
        definition = self._agents.get("supervisor")
        binding = bind_agent_tools(
            self._tools,
            definition,
            ToolContext(task_id=task_id),
        )
        loop = AgentLoop(
            provider=self._gateway.model_turn_provider(),
            model=definition.model,
            system=structured_output_system(
                self._agents.prompt("supervisor", phase),
                output_model,
            ),
            tools=binding.schemas if binding is not None else (),
            executor=binding.executor if binding is not None else None,
            config=AgentLoopConfig(),
        )
        completed = await loop.prompt(json.dumps(context, ensure_ascii=False, sort_keys=True))
        raw_content = completed.content
        if isinstance(raw_content, str):
            text = raw_content
        elif isinstance(raw_content, tuple):
            text = anthropic_text(raw_content)
        else:
            text = None
        parsed = parse_structured_output(text, output_model)
        if completed.usage is None:
            raise RuntimeError("Supervisor AgentLoop returned no model usage")
        await self._record_invocation(
            agent_id="supervisor",
            phase=phase,
            output=parsed,
            usage=completed.usage,
        )
        return parsed

    async def _record_invocation(
        self,
        *,
        agent_id: str,
        phase: str,
        output: BaseModel,
        usage: ModelUsage,
    ) -> None:
        invocation = AgentInvocation(
            agent_id=agent_id,
            output=output.model_dump(mode="json"),
            usage=usage,
            source_id=str(uuid4()),
            phase=phase,
            message_type="agent_message",
        )
        self._invocations.append(invocation)
        if self._message_sink is not None:
            await self._message_sink(invocation)
