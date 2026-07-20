from dataclasses import dataclass
from typing import Any, Protocol

from app.contracts.agents import (
    AgentProposal,
    DesignFeedback,
    ReviewFeedback,
    VerificationReport,
)
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
    async def architect(self, task: TaskContract) -> AgentProposal: ...

    async def reviewer(
        self,
        task: TaskContract,
        architecture: AgentProposal,
    ) -> ReviewFeedback: ...

    async def designer(
        self,
        task: TaskContract,
        architecture: AgentProposal,
        review: ReviewFeedback,
    ) -> DesignFeedback: ...

    async def planner(
        self,
        task: TaskContract,
        architecture: AgentProposal,
        review: ReviewFeedback,
        design: DesignFeedback,
        workspace_files: frozenset[str] = frozenset(),
    ) -> ExecutionPlan: ...

    async def replanner(
        self,
        task: TaskContract,
        prior_plan: ExecutionPlan,
        verification: VerificationReport,
        evidence: tuple[dict[str, Any], ...],
        workspace_files: frozenset[str],
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
    architecture: AgentProposal
    review: ReviewFeedback
    design: DesignFeedback
    plan: ExecutionPlan


class Scheduler:
    def __init__(self, runtime: AgentRuntime) -> None:
        self._runtime = runtime

    async def deliberate(
        self,
        task: TaskContract,
        workspace_files: frozenset[str] = frozenset(),
    ) -> DeliberationResult:
        architecture = await self._runtime.architect(task)
        review = await self._runtime.reviewer(task, architecture)
        design = await self._runtime.designer(task, architecture, review)
        plan = await self._runtime.planner(
            task,
            architecture,
            review,
            design,
            workspace_files,
        )
        return DeliberationResult(
            architecture=architecture,
            review=review,
            design=design,
            plan=plan,
        )
