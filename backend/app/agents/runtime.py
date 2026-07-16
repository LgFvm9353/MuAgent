import json
from typing import Any, Protocol, cast

from pydantic import BaseModel

from app.contracts.agents import (
    AgentDecision,
    AgentProposal,
    Critique,
    CritiqueSet,
    VerificationReport,
)
from app.contracts.execution import ExecutionPlan
from app.contracts.task import TaskContract
from app.harness.context import ContextBuilder
from app.harness.model_gateway import ModelResult
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


class AgentRuntime:
    def __init__(
        self,
        gateway: StructuredGateway,
        agents: AgentRegistry,
        tools: ToolRegistry,
    ) -> None:
        self._gateway = gateway
        self._agents = agents
        self._tools = tools
        self._context = ContextBuilder()
        self._invocations: list[AgentInvocation] = []

    def drain_invocations(self) -> tuple[AgentInvocation, ...]:
        invocations = tuple(self._invocations)
        self._invocations.clear()
        return invocations

    async def analyst(self, task: TaskContract) -> AgentProposal:
        return cast(
            AgentProposal, await self._call("analyst", self._context.analyst(task), AgentProposal)
        )

    async def domain_expert(self, task: TaskContract) -> AgentProposal:
        catalog = self._tools.catalog(task.allowed_tools)
        return cast(
            AgentProposal,
            await self._call(
                "domain_expert", self._context.domain_expert(task, catalog), AgentProposal
            ),
        )

    async def revise(
        self,
        agent_id: str,
        task: TaskContract,
        proposal: AgentProposal,
        feedback: tuple[str, ...],
    ) -> AgentProposal:
        if agent_id not in {"analyst", "domain_expert"}:
            raise ValueError("only proposal agents can revise")
        context = {
            "task": self._context.analyst(task),
            "previous_proposal": proposal.model_dump(mode="json"),
            "required_revisions": feedback,
            "instruction": "Revise only the disputed points without expanding scope.",
        }
        return cast(AgentProposal, await self._call(agent_id, context, AgentProposal))

    async def critic(
        self, task: TaskContract, proposals: tuple[AgentProposal, ...]
    ) -> tuple[Critique, ...]:
        context = self._context.critic(
            task, tuple(item.model_dump(mode="json") for item in proposals)
        )
        result = cast(CritiqueSet, await self._call("critic", context, CritiqueSet))
        return result.critiques

    async def judge(
        self,
        task: TaskContract,
        proposals: tuple[AgentProposal, ...],
        critiques: tuple[Critique, ...],
    ) -> AgentDecision:
        del task
        context = self._context.judge(
            tuple(item.model_dump(mode="json") for item in proposals),
            tuple(item.model_dump(mode="json") for item in critiques),
        )
        return cast(AgentDecision, await self._call("judge", context, AgentDecision))

    async def planner(self, task: TaskContract, decision: AgentDecision) -> ExecutionPlan:
        context = self._context.planner(
            decision.model_dump(mode="json"), self._tools.catalog(task.allowed_tools)
        )
        return cast(ExecutionPlan, await self._call("planner", context, ExecutionPlan))

    async def replanner(
        self,
        task: TaskContract,
        decision: AgentDecision,
        prior_plan: ExecutionPlan,
        verification: VerificationReport,
        evidence: tuple[dict[str, Any], ...],
    ) -> ExecutionPlan:
        context = self._context.replanner(
            decision.model_dump(mode="json"),
            prior_plan.model_dump(mode="json"),
            verification.model_dump(mode="json"),
            evidence,
            self._tools.catalog(task.allowed_tools),
        )
        return cast(ExecutionPlan, await self._call("planner", context, ExecutionPlan))

    async def verifier(
        self,
        task: TaskContract,
        plan: ExecutionPlan,
        evidence: tuple[dict[str, Any], ...],
    ) -> VerificationReport:
        context = self._context.verifier(task, plan.model_dump(mode="json"), (), evidence)
        return cast(VerificationReport, await self._call("verifier", context, VerificationReport))

    async def _call(
        self,
        agent_id: str,
        context: dict[str, Any],
        output_model: type[AgentProposal]
        | type[CritiqueSet]
        | type[AgentDecision]
        | type[ExecutionPlan]
        | type[VerificationReport],
    ) -> object:
        definition = self._agents.get(agent_id)
        result = await self._gateway.structured(
            model=definition.model,
            system=self._agents.prompt(agent_id),
            user_content=json.dumps(context, ensure_ascii=False, sort_keys=True),
            output_model=output_model,
        )
        if result.parsed_output is None:
            raise RuntimeError(f"agent returned no structured output: {agent_id}")
        self._invocations.append(
            AgentInvocation(
                agent_id=agent_id,
                output=result.parsed_output.model_dump(mode="json"),
                usage=result.usage,
            )
        )
        return result.parsed_output
