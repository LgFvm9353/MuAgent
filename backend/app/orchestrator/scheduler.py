import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

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


CollaborationSink = Callable[[AgentInvocation], Awaitable[None]]


class SpecialistQuorumError(RuntimeError):
    """Raised when neither parallel specialist produces a usable result."""


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
    ) -> DesignFeedback: ...

    async def planner(
        self,
        task: TaskContract,
        architecture: AgentProposal,
        review: ReviewFeedback | None,
        design: DesignFeedback | None,
        workspace_files: frozenset[str] = frozenset(),
        specialist_failures: tuple[str, ...] = (),
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
    def __init__(
        self,
        runtime: AgentRuntime,
        collaboration_sink: CollaborationSink | None = None,
    ) -> None:
        self._runtime = runtime
        self._collaboration_sink = collaboration_sink

    async def deliberate(
        self,
        task: TaskContract,
        workspace_files: frozenset[str] = frozenset(),
    ) -> DeliberationResult:
        architecture = await self._runtime.architect(task)
        await self._publish(
            "architect",
            "delegation",
            "@Reviewer 请审查技术风险与测试策略；@Designer 请设计产品与交互方案。",
            {"from_agent": "architect", "target_agents": ["reviewer", "designer"]},
        )

        async with asyncio.TaskGroup() as group:
            review_task = group.create_task(
                self._run_specialist("reviewer", self._runtime.reviewer(task, architecture))
            )
            design_task = group.create_task(
                self._run_specialist("designer", self._runtime.designer(task, architecture))
            )

        review_result = review_task.result()
        design_result = design_task.result()
        failures = tuple(
            result.error
            for result in (review_result, design_result)
            if result.error is not None
        )
        review = review_result.value if isinstance(review_result.value, ReviewFeedback) else None
        design = design_result.value if isinstance(design_result.value, DesignFeedback) else None
        if review is None and design is None:
            raise SpecialistQuorumError("Reviewer and Designer both failed: " + "; ".join(failures))

        await self._publish(
            "architect",
            "synthesis",
            "已收到专家结果，Architect 正在汇总执行计划。",
            {
                "from_agent": "architect",
                "completed_agents": [
                    agent_id
                    for agent_id, value in (("reviewer", review), ("designer", design))
                    if value is not None
                ],
                "specialist_failures": list(failures),
            },
        )
        plan = await self._runtime.planner(
            task,
            architecture,
            review,
            design,
            workspace_files,
            failures,
        )
        return DeliberationResult(
            architecture=architecture,
            review=review,
            design=design,
            specialist_failures=failures,
            plan=plan,
        )

    async def _run_specialist(
        self,
        agent_id: str,
        operation: Awaitable[ReviewFeedback | DesignFeedback],
    ) -> _SpecialistResult:
        try:
            value = await operation
        except asyncio.CancelledError:
            raise
        except Exception as error:
            summary = f"{agent_id} 执行失败，协作流程将按法定人数规则继续。"
            await self._publish(
                agent_id,
                "specialist_failed",
                summary,
                {"from_agent": agent_id, "target_agents": ["architect"], "status": "failed"},
            )
            return _SpecialistResult(agent_id=agent_id, value=None, error=f"{agent_id}: {error}")

        await self._publish(
            agent_id,
            "handoff",
            f"@Architect {agent_id} 已完成并提交结果。",
            {"from_agent": agent_id, "target_agents": ["architect"], "status": "completed"},
        )
        return _SpecialistResult(agent_id=agent_id, value=value)

    async def _publish(
        self,
        agent_id: str,
        phase: str,
        summary: str,
        output: dict[str, Any],
    ) -> None:
        if self._collaboration_sink is None:
            return
        await self._collaboration_sink(
            AgentInvocation(
                agent_id=agent_id,
                output={"summary": summary, **output},
                usage=ModelUsage(
                    request_id=None,
                    model="orchestrator",
                    stop_reason=None,
                    input_tokens=0,
                    output_tokens=0,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                    latency_ms=0,
                    retry_count=0,
                ),
                source_id=str(uuid4()),
                phase=phase,
                message_type="collaboration",
            )
        )
