import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, cast
from uuid import uuid4

from pydantic import BaseModel

from app.contracts.agents import AgentProposal, DesignFeedback, ReviewFeedback, VerificationReport
from app.contracts.execution import ExecutionPlan
from app.contracts.task import TaskContract
from app.harness.context import ContextBuilder
from app.harness.model_gateway import ModelResult, ModelToolCallPort
from app.harness.registry import AgentRegistry
from app.orchestrator.scheduler import AgentInvocation
from app.tools.registry import ToolRegistry


class StructuredGateway(Protocol):
    async def structured(
        self,
        *,
        model: str,
        system: str,
        user_content: str,
        output_model: type[BaseModel],
        max_tokens: int = 16_000,
        effort: str = "high",
    ) -> ModelResult: ...
    async def structured_with_tools(
        self,
        *,
        model: str,
        system: str,
        user_content: str,
        output_model: type[BaseModel],
        tools: tuple[dict[str, Any], ...],
        executor: ModelToolCallPort,
        max_tool_rounds: int = 6,
        max_tokens: int = 16_000,
        effort: str = "high",
    ) -> ModelResult: ...


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

    async def architect(self, task: TaskContract) -> AgentProposal:
        return cast(
            AgentProposal,
            await self._call("architect", "analysis", self._context.architect(task), AgentProposal),
        )

    async def reviewer(
        self,
        task: TaskContract,
        architecture: AgentProposal,
    ) -> ReviewFeedback:
        context = self._context.reviewer(task, architecture.model_dump(mode="json"))
        return cast(
            ReviewFeedback,
            await self._call("reviewer", "review", context, ReviewFeedback),
        )

    async def designer(
        self,
        task: TaskContract,
        architecture: AgentProposal,
    ) -> DesignFeedback:
        context = self._context.designer(
            task,
            architecture.model_dump(mode="json"),
        )
        return cast(
            DesignFeedback,
            await self._call("designer", "design", context, DesignFeedback),
        )

    async def planner(
        self,
        task: TaskContract,
        architecture: AgentProposal,
        review: ReviewFeedback | None,
        design: DesignFeedback | None,
        workspace_files: frozenset[str] = frozenset(),
        specialist_failures: tuple[str, ...] = (),
    ) -> ExecutionPlan:
        context = self._context.planner(
            task,
            architecture.model_dump(mode="json"),
            review.model_dump(mode="json") if review is not None else None,
            design.model_dump(mode="json") if design is not None else None,
            self._tools.catalog(task.allowed_tools),
            workspace_files,
            specialist_failures,
        )
        return cast(
            ExecutionPlan,
            await self._call("architect", "planning", context, ExecutionPlan),
        )

    async def replanner(
        self,
        task: TaskContract,
        prior_plan: ExecutionPlan,
        verification: VerificationReport,
        evidence: tuple[dict[str, Any], ...],
        workspace_files: frozenset[str],
    ) -> ExecutionPlan:
        context = self._context.replanner(
            task,
            prior_plan.model_dump(mode="json"),
            verification.model_dump(mode="json"),
            evidence,
            self._tools.catalog(task.allowed_tools),
            workspace_files,
        )
        return cast(
            ExecutionPlan,
            await self._call("architect", "replanning", context, ExecutionPlan),
        )

    async def verifier(
        self,
        task: TaskContract,
        plan: ExecutionPlan,
        execution: tuple[dict[str, Any], ...],
        evidence: tuple[dict[str, Any], ...],
        artifacts: tuple[dict[str, Any], ...],
    ) -> VerificationReport:
        context = self._context.verifier(
            task,
            plan.model_dump(mode="json"),
            execution,
            evidence,
            artifacts,
        )
        return cast(
            VerificationReport,
            await self._call("reviewer", "verification", context, VerificationReport),
        )

    async def _call(
        self,
        agent_id: str,
        phase: str | dict[str, Any],
        context: dict[str, Any]
        | type[AgentProposal]
        | type[ReviewFeedback]
        | type[DesignFeedback]
        | type[ExecutionPlan]
        | type[VerificationReport],
        output_model: type[AgentProposal]
        | type[ReviewFeedback]
        | type[DesignFeedback]
        | type[ExecutionPlan]
        | type[VerificationReport]
        | None = None,
    ) -> object:
        if isinstance(phase, dict):
            if not isinstance(context, type) or output_model is not None:
                raise TypeError("legacy agent call requires context and output model")
            output_model = context
            context = phase
            phase = "analysis"
        if output_model is None or not isinstance(context, dict):
            raise TypeError("agent call requires context and output model")
        definition = self._agents.get(agent_id)
        result = await self._gateway.structured(
            model=definition.model,
            system=self._agents.prompt(agent_id, phase),
            user_content=json.dumps(context, ensure_ascii=False, sort_keys=True),
            output_model=output_model,
        )
        if result.parsed_output is None:
            raise RuntimeError(f"agent returned no structured output: {agent_id}")
        invocation = AgentInvocation(
            agent_id=agent_id,
            output=result.parsed_output.model_dump(mode="json"),
            usage=result.usage,
            source_id=str(uuid4()),
            phase=phase,
            message_type="agent_message",
        )
        self._invocations.append(invocation)
        if self._message_sink is not None:
            await self._message_sink(invocation)
        return result.parsed_output
