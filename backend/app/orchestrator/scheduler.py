import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from app.agents.retry import is_retryable_agent_error, retry_delay_seconds
from app.contracts.agents import AgentBrief, VerificationReport
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
    async def specialist(
        self,
        agent_id: str,
        task: TaskContract,
        role_context: dict[str, Any] | None = None,
    ) -> AgentBrief: ...

    async def planner(
        self,
        task: TaskContract,
        briefs: tuple[AgentBrief, ...],
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
    briefs: tuple[AgentBrief, ...]
    specialist_failures: tuple[str, ...]
    plan: ExecutionPlan


@dataclass(frozen=True, slots=True)
class _SpecialistResult:
    agent_id: str
    value: AgentBrief | None
    error: str | None = None


class Scheduler:
    """Fan out a dynamically selected set of independent specialists.

    This is deliberately a parent/child workflow: every specialist receives the
    same immutable task snapshot, runs concurrently, and returns an ``AgentBrief``.
    The parent then invokes ``planner`` once to synthesize those briefs into an
    executable plan.  No child invokes another child and there is no serial
    handoff queue.
    """

    _SIDE_EFFECT_TERMS = (
        "modify",
        "change",
        "edit",
        "write",
        "create",
        "delete",
        "remove",
        "implement",
        "fix",
        "run",
        "execute",
        "实现",
        "修改",
        "修复",
        "编写",
        "执行",
    )
    _RESEARCH_TERMS = (
        "documentation",
        "docs",
        "official",
        "latest",
        "version",
        "standard",
        "research",
        "文档",
        "官方",
        "最新",
        "版本",
        "规范",
        "资料",
    )
    _REVIEW_TERMS = (
        "review",
        "test",
        "testing",
        "security",
        "risk",
        "audit",
        "verify",
        "审查",
        "测试",
        "安全",
        "风险",
        "审计",
        "验证",
    )
    _CONTEXT_TERMS = (
        "refactor",
        "rewrite",
        "migration",
        "large",
        "complex",
        "handoff",
        "重构",
        "迁移",
        "大型",
        "复杂",
        "交接",
        "全局",
    )
    _ORACLE_TERMS = (
        "should we",
        "compare",
        "tradeoff",
        "alternative",
        "uncertain",
        "decision",
        "是否",
        "比较",
        "权衡",
        "方案",
        "不确定",
        "决策",
    )

    def __init__(
        self,
        runtime: AgentRuntime,
        collaboration_sink: CollaborationSink | None = None,
        max_specialists: int = 8,
    ) -> None:
        if max_specialists < 1:
            raise ValueError("max_specialists must be positive")
        self._runtime = runtime
        self._collaboration_sink = collaboration_sink
        self._max_specialists = max_specialists

    async def deliberate(
        self,
        task: TaskContract,
        workspace_files: frozenset[str] = frozenset(),
    ) -> DeliberationResult:
        specialist_ids = self.select_specialists(task)
        await self._publish(
            "parent",
            "fanout",
            "Parent selected independent specialists",
            {"selected_agents": list(specialist_ids), "status": "running"},
        )
        async with asyncio.TaskGroup() as group:
            children = tuple(
                group.create_task(
                    self._run_specialist(
                        agent_id,
                        task,
                        {"workspace_files": sorted(workspace_files)},
                    )
                )
                for agent_id in specialist_ids
            )
        results = tuple(child.result() for child in children)
        briefs = tuple(result.value for result in results if result.value is not None)
        failures = tuple(result.error for result in results if result.error is not None)
        if not briefs:
            raise SpecialistQuorumError("parallel specialists produced no usable result")
        await self._publish(
            "parent",
            "synthesis",
            "Parent is aggregating specialist briefs",
            {
                "completed_agents": [
                    result.agent_id for result in results if result.value is not None
                ],
                "specialist_failures": list(failures),
                "status": "running",
            },
        )
        plan = await self._runtime.planner(task, briefs, workspace_files, failures)
        return DeliberationResult(briefs, failures, plan)

    def select_specialists(self, task: TaskContract) -> tuple[str, ...]:
        """Choose capabilities from the task rather than starting a fixed team."""
        text = " ".join(
            (
                task.goal,
                *task.constraints,
                *(criterion.description for criterion in task.acceptance_criteria),
            )
        ).casefold()
        selected: list[str] = []

        def add(agent_id: str) -> None:
            if (
                agent_id not in selected
                and agent_id != "planner"
                and len(selected) < self._max_specialists
            ):
                selected.append(agent_id)

        # Repository reconnaissance is the cheapest useful first perspective for
        # implementation tasks, while pure questions can be handled by delegate.
        has_execution = any(term.casefold() in text for term in self._SIDE_EFFECT_TERMS)
        has_research = any(term.casefold() in text for term in self._RESEARCH_TERMS)
        has_review = any(term.casefold() in text for term in self._REVIEW_TERMS)
        has_context = any(term.casefold() in text for term in self._CONTEXT_TERMS)
        has_oracle = any(term.casefold() in text for term in self._ORACLE_TERMS)

        if has_context:
            add("context-builder")
        if has_research:
            add("researcher")
        if has_execution:
            add("scout")
            add("worker")
        if has_review:
            add("reviewer")
        if has_oracle:
            add("oracle")
        if not selected:
            add("delegate")
        return tuple(selected)

    async def _run_specialist(
        self,
        agent_id: str,
        task: TaskContract,
        role_context: dict[str, Any],
    ) -> _SpecialistResult:
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            await self._publish(
                agent_id,
                "specialist",
                f"{agent_id} started (attempt {attempt}/{max_attempts})",
                {"status": "running", "attempt": attempt, "max_attempts": max_attempts},
            )
            try:
                value = await self._runtime.specialist(
                    agent_id,
                    task,
                    {**role_context, "attempt": attempt, "max_attempts": max_attempts},
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if attempt < max_attempts and is_retryable_agent_error(error):
                    await self._publish(
                        agent_id,
                        "specialist_retrying",
                        f"{agent_id} retry scheduled",
                        {"status": "retrying", "attempt": attempt, "error": str(error)},
                    )
                    await asyncio.sleep(retry_delay_seconds(attempt))
                    continue
                await self._publish(
                    agent_id,
                    "specialist_failed",
                    f"{agent_id} failed after {attempt} attempt(s)",
                    {
                        "status": "failed",
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "error": str(error),
                    },
                )
                return _SpecialistResult(agent_id, None, f"{agent_id}: {error}")
            await self._publish(
                agent_id,
                "specialist_completed",
                f"{agent_id} completed",
                {"status": "completed", "attempt": attempt},
            )
            return _SpecialistResult(agent_id, value)
        raise AssertionError("specialist retry loop exited without a result")

    async def _publish(
        self, agent_id: str, phase: str, summary: str, output: dict[str, Any]
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
