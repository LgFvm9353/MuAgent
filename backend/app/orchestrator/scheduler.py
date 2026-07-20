from dataclasses import dataclass
from typing import Any, Protocol

from app.contracts.agents import AgentProposal, VerificationReport
from app.contracts.execution import ExecutionPlan
from app.contracts.task import TaskContract
from app.harness.model_gateway import ModelUsage


@dataclass(frozen=True, slots=True)
class AgentInvocation:
    agent_id: str
    output: dict[str, Any]
    usage: ModelUsage
    source_id: str
    phase: str
    message_type: str


class AgentRuntime(Protocol):
    async def analyst(self, task: TaskContract) -> AgentProposal: ...

    async def planner(
        self,
        task: TaskContract,
        analysis: AgentProposal,
        workspace_files: frozenset[str] = frozenset(),
    ) -> ExecutionPlan: ...

    async def replanner(
        self,
        task: TaskContract,
        prior_plan: ExecutionPlan,
        verification: VerificationReport,
        evidence: tuple[dict[str, Any], ...],
    ) -> ExecutionPlan: ...

    async def verifier(
        self,
        task: TaskContract,
        plan: ExecutionPlan,
        execution: tuple[dict[str, Any], ...],
        evidence: tuple[dict[str, Any], ...],
        artifacts: tuple[dict[str, Any], ...],
    ) -> VerificationReport: ...

    def drain_invocations(self) -> tuple[AgentInvocation, ...]: ...


@dataclass(frozen=True, slots=True)
class DeliberationResult:
    analysis: AgentProposal
    plan: ExecutionPlan


class Scheduler:
    def __init__(self, runtime: AgentRuntime) -> None:
        self._runtime = runtime

    async def deliberate(
        self,
        task: TaskContract,
        workspace_files: frozenset[str] = frozenset(),
    ) -> DeliberationResult:
        analysis = await self._runtime.analyst(task)
        plan = await self._runtime.planner(task, analysis, workspace_files)
        return DeliberationResult(analysis=analysis, plan=plan)
