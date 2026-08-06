import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from app.contracts.agents import AgentProposal, DesignFeedback, ReviewFeedback, VerificationReport
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


CollaborationSink = Callable[[AgentInvocation], Awaitable[None]]


class SpecialistQuorumError(RuntimeError):
    """Raised when no usable child result is available for parent synthesis."""


class AgentRuntime(Protocol):
    async def architect(self, task: TaskContract) -> AgentProposal: ...
    async def reviewer(self, task: TaskContract, architecture: AgentProposal | None = None) -> ReviewFeedback: ...
    async def designer(self, task: TaskContract, architecture: AgentProposal | None = None) -> DesignFeedback: ...
    async def planner(self, task: TaskContract, architecture: AgentProposal, review: ReviewFeedback | None, design: DesignFeedback | None, workspace_files: frozenset[str] = frozenset(), specialist_failures: tuple[str, ...] = ()) -> ExecutionPlan: ...
    async def replanner(self, task: TaskContract, prior_plan: ExecutionPlan, verification: VerificationReport, evidence: tuple[dict[str, Any], ...], workspace_files: frozenset[str]) -> ExecutionPlan: ...
    async def verifier(self, task: TaskContract, plan: ExecutionPlan, execution: tuple[dict[str, Any], ...], evidence: tuple[dict[str, Any], ...], artifacts: tuple[dict[str, Any], ...]) -> VerificationReport: ...
    def drain_invocations(self) -> tuple[AgentInvocation, ...]: ...


@dataclass(frozen=True, slots=True)
class DeliberationResult:
    architecture: AgentProposal
    review: ReviewFeedback | None
    design: DesignFeedback | None
    specialist_failures: tuple[str, ...]
    plan: ExecutionPlan


@dataclass(frozen=True, slots=True)
class _SpecialistResult:
    agent_id: str
    value: ReviewFeedback | DesignFeedback | None
    error: str | None = None


class Scheduler:
    """Parent/child fan-out scheduler.

    Architect, reviewer and designer are independent fresh children. They all
    receive the same task snapshot and never call or depend on one another.
    The parent performs deterministic aggregation and invokes the planner as a
    synthesis step; this is not a child-to-child serial workflow.
    """

    def __init__(self, runtime: AgentRuntime, collaboration_sink: CollaborationSink | None = None) -> None:
        self._runtime = runtime
        self._collaboration_sink = collaboration_sink

    async def deliberate(self, task: TaskContract, workspace_files: frozenset[str] = frozenset()) -> DeliberationResult:
        async with asyncio.TaskGroup() as group:
            architect_task = group.create_task(self._run_architect(task))
            review_task = group.create_task(self._run_specialist("reviewer", "review", self._runtime.reviewer(task, None)))
            design_task = group.create_task(self._run_specialist("designer", "design", self._runtime.designer(task, None)))

        architecture = architect_task.result()
        review_result = review_task.result()
        design_result = design_task.result()
        review = review_result.value if isinstance(review_result.value, ReviewFeedback) else None
        design = design_result.value if isinstance(design_result.value, DesignFeedback) else None
        failures = tuple(result.error for result in (review_result, design_result) if result.error)
        if review is None and design is None:
            raise SpecialistQuorumError("parallel specialist children produced no usable result")
        await self._publish("parent", "synthesis", "Parent is aggregating parallel child results", {
            "completed_agents": [name for name, value in (("architect", architecture), ("reviewer", review), ("designer", design)) if value is not None],
            "specialist_failures": list(failures),
            "status": "running",
        })
        plan = await self._runtime.planner(task, architecture, review, design, workspace_files, failures)
        return DeliberationResult(architecture, review, design, failures, plan)

    async def _run_architect(self, task: TaskContract) -> AgentProposal:
        await self._publish("architect", "analysis", "architect child started", {"status": "running"})
        value = await self._runtime.architect(task)
        await self._publish("architect", "analysis_completed", "architect child completed", {"status": "completed"})
        return value

    async def _run_specialist(self, agent_id: str, phase: str, operation: Awaitable[ReviewFeedback | DesignFeedback]) -> _SpecialistResult:
        await self._publish(agent_id, phase, f"{agent_id} child started", {"status": "running"})
        try:
            value = await operation
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self._publish(agent_id, "child_failed", f"{agent_id} child failed", {"status": "failed"})
            return _SpecialistResult(agent_id, None, f"{agent_id}: {error}")
        await self._publish(agent_id, "child_completed", f"{agent_id} child completed", {"status": "completed"})
        return _SpecialistResult(agent_id, value)

    async def _publish(self, agent_id: str, phase: str, summary: str, output: dict[str, Any]) -> None:
        if self._collaboration_sink is None:
            return
        await self._collaboration_sink(AgentInvocation(
            agent_id=agent_id,
            output={"summary": summary, **output},
            usage=ModelUsage(request_id=None, model="orchestrator", stop_reason=None, input_tokens=0, output_tokens=0, cache_creation_input_tokens=0, cache_read_input_tokens=0, latency_ms=0, retry_count=0),
            source_id=str(uuid4()),
            phase=phase,
            message_type="collaboration",
        ))
