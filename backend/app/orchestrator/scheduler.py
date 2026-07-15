import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.contracts.agents import AgentDecision, AgentProposal, Critique, VerificationReport
from app.contracts.execution import ExecutionPlan
from app.contracts.task import TaskContract
from app.harness.model_gateway import ModelUsage


@dataclass(frozen=True, slots=True)
class AgentInvocation:
    agent_id: str
    output: dict[str, Any]
    usage: ModelUsage


class AgentRuntime(Protocol):
    async def analyst(self, task: TaskContract) -> AgentProposal: ...
    async def domain_expert(self, task: TaskContract) -> AgentProposal: ...
    async def critic(
        self, task: TaskContract, proposals: tuple[AgentProposal, ...]
    ) -> tuple[Critique, ...]: ...
    async def revise(
        self,
        agent_id: str,
        task: TaskContract,
        proposal: AgentProposal,
        feedback: tuple[str, ...],
    ) -> AgentProposal: ...
    async def judge(
        self,
        task: TaskContract,
        proposals: tuple[AgentProposal, ...],
        critiques: tuple[Critique, ...],
    ) -> AgentDecision: ...
    async def planner(self, task: TaskContract, decision: AgentDecision) -> ExecutionPlan: ...
    async def replanner(
        self,
        task: TaskContract,
        decision: AgentDecision,
        prior_plan: ExecutionPlan,
        verification: VerificationReport,
        evidence: tuple[dict[str, Any], ...],
    ) -> ExecutionPlan: ...
    async def verifier(
        self, task: TaskContract, plan: ExecutionPlan, evidence: tuple[dict[str, Any], ...]
    ) -> VerificationReport: ...
    def drain_invocations(self) -> tuple[AgentInvocation, ...]: ...


@dataclass(frozen=True, slots=True)
class DeliberationResult:
    proposals: tuple[AgentProposal, ...]
    critiques: tuple[Critique, ...]
    decision: AgentDecision
    plan: ExecutionPlan


class Scheduler:
    def __init__(self, runtime: AgentRuntime) -> None:
        self._runtime = runtime
        self._active: dict[UUID, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def deliberate(self, task: TaskContract) -> DeliberationResult:
        analyst: AgentProposal | None = None
        expert: AgentProposal | None = None

        async def run_analyst() -> None:
            nonlocal analyst
            analyst = await self._runtime.analyst(task)

        async def run_expert() -> None:
            nonlocal expert
            expert = await self._runtime.domain_expert(task)

        async with asyncio.TaskGroup() as group:
            group.create_task(run_analyst(), name=f"analyst:{task.task_id}")
            group.create_task(run_expert(), name=f"domain-expert:{task.task_id}")
        if analyst is None or expert is None:
            raise RuntimeError("parallel analysis did not produce both proposals")
        proposals: tuple[AgentProposal, ...] = (analyst, expert)
        critiques = await self._runtime.critic(task, proposals)
        no_information_rounds = 0
        for _ in range(task.budget.max_revisions):
            feedback_by_index = {
                critique.proposal_index: critique.required_revisions
                for critique in critiques
                if critique.required_revisions
            }
            if not feedback_by_index:
                break
            revised = list(proposals)
            changed = False
            for index, feedback in feedback_by_index.items():
                if index >= len(revised):
                    raise RuntimeError("critic referenced an unknown proposal")
                agent_id = ("analyst", "domain_expert")[index]
                candidate = await self._runtime.revise(
                    agent_id,
                    task,
                    revised[index],
                    feedback,
                )
                changed = changed or candidate != revised[index]
                revised[index] = candidate
            proposals = tuple(revised)
            no_information_rounds = 0 if changed else no_information_rounds + 1
            if no_information_rounds >= 2:
                raise RuntimeError("discussion produced no new valid information")
            critiques = await self._runtime.critic(task, proposals)
        decision = await self._runtime.judge(task, proposals, critiques)
        if not decision.may_plan:
            raise RuntimeError("judge did not approve planning")
        plan = await self._runtime.planner(task, decision)
        return DeliberationResult(
            proposals=proposals,
            critiques=critiques,
            decision=decision,
            plan=plan,
        )

    async def start(self, task_id: UUID, operation: Coroutine[Any, Any, None]) -> None:
        async with self._lock:
            current = self._active.get(task_id)
            if current is not None and not current.done():
                raise RuntimeError(f"task is already scheduled: {task_id}")
            scheduled = asyncio.create_task(operation, name=f"orchestrator:{task_id}")
            self._active[task_id] = scheduled

            def remove_finished(finished: asyncio.Task[None]) -> None:
                if self._active.get(task_id) is finished:
                    self._active.pop(task_id, None)

            scheduled.add_done_callback(remove_finished)

    async def cancel(self, task_id: UUID) -> bool:
        async with self._lock:
            task = self._active.get(task_id)
            if task is None or task.done():
                return False
            task.cancel()
            return True
