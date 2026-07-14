from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.execution import ExecutionPlan, ExecutionStep
from app.contracts.task import TaskContract
from app.harness.pricing import estimate_cost
from app.harness.registry import AgentRegistry
from app.models import (
    AgentRun,
    EvidenceRecordModel,
    ExecutionPlanRecord,
    ExecutionStepRecord,
    Task,
    ToolCall,
    UsageRecord,
    VerificationReportModel,
)
from app.orchestrator.scheduler import AgentRuntime
from app.orchestrator.state_machine import TaskState
from app.repositories import TaskRepository
from app.tools.executor import ToolExecutor, idempotency_key


class ExecutionService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        runtime: AgentRuntime,
        agents: AgentRegistry,
        executor: ToolExecutor,
    ) -> None:
        self._sessions = sessions
        self._runtime = runtime
        self._agents = agents
        self._executor = executor

    async def execute(self, task_id: UUID) -> None:
        contract, plan = await self._load(task_id)
        evidence: list[dict[str, Any]] = []
        completed: set[str] = set()
        remaining = {step.step_id: step for step in plan.steps}
        while remaining:
            ready = [step for step in remaining.values() if step.depends_on <= completed]
            if not ready:
                raise RuntimeError("execution plan has no runnable step")
            for step in ready:
                await self._check_cancelled(task_id)
                record = await self._execute_step(task_id, plan.version, step)
                evidence.append(record)
                completed.add(step.step_id)
                remaining.pop(step.step_id)

        async with self._sessions() as session:
            repository = TaskRepository(session)
            task = await repository.get(task_id, for_update=True)
            await repository.transition(
                task_id,
                TaskState.VERIFYING,
                expected_version=task.version,
                trace_id=task.trace_id,
                reason="all execution steps completed",
            )
            await session.commit()

        report = await self._runtime.verifier(contract, plan, tuple(evidence))
        async with self._sessions() as session:
            repository = TaskRepository(session)
            task = await repository.get(task_id, for_update=True)
            for invocation in self._runtime.drain_invocations():
                definition = self._agents.get(invocation.agent_id)
                run = AgentRun(
                    task_id=task_id,
                    agent_id=invocation.agent_id,
                    prompt_version=definition.prompt_version,
                    schema_version=definition.schema_version,
                    model=definition.model,
                    config_hash=definition.config_hash(),
                    status="succeeded",
                    output=invocation.output,
                )
                session.add(run)
                await session.flush()
                usage = invocation.usage
                session.add(
                    UsageRecord(
                        task_id=task_id,
                        agent_run_id=run.id,
                        request_id=usage.request_id,
                        model=usage.model,
                        stop_reason=usage.stop_reason,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        cache_creation_input_tokens=usage.cache_creation_input_tokens,
                        cache_read_input_tokens=usage.cache_read_input_tokens,
                        latency_ms=usage.latency_ms,
                        retry_count=usage.retry_count,
                        estimated_cost_usd=float(
                            estimate_cost(
                                usage.model,
                                input_tokens=usage.input_tokens,
                                output_tokens=usage.output_tokens,
                                cache_creation_input_tokens=usage.cache_creation_input_tokens,
                                cache_read_input_tokens=usage.cache_read_input_tokens,
                            )
                        ),
                    )
                )
            session.add(
                VerificationReportModel(
                    task_id=task_id,
                    plan_id=plan.plan_id,
                    verdict=report.verdict,
                    content=report.model_dump(mode="json"),
                )
            )
            target = {
                "passed": TaskState.SUCCEEDED,
                "failed": TaskState.FAILED,
                "needs_review": TaskState.NEEDS_REVIEW,
            }[report.verdict]
            await repository.transition(
                task_id,
                target,
                expected_version=task.version,
                trace_id=task.trace_id,
                reason=f"verifier verdict: {report.verdict}",
            )
            await session.commit()

    async def _load(self, task_id: UUID) -> tuple[TaskContract, ExecutionPlan]:
        async with self._sessions() as session:
            task = await session.get(Task, task_id)
            if task is None or task.state != TaskState.EXECUTING.value:
                raise RuntimeError("task is not executable")
            plan_record = await session.scalar(
                select(ExecutionPlanRecord)
                .where(ExecutionPlanRecord.task_id == task_id)
                .order_by(ExecutionPlanRecord.version.desc())
                .limit(1)
            )
            if plan_record is None:
                raise RuntimeError("task has no execution plan")
            return TaskContract.model_validate(task.contract), ExecutionPlan.model_validate(plan_record.content)

    async def _check_cancelled(self, task_id: UUID) -> None:
        async with self._sessions() as session:
            task = await session.get(Task, task_id)
            if task is None or task.cancel_requested:
                raise RuntimeError("task execution cancelled")

    async def _execute_step(
        self,
        task_id: UUID,
        plan_version: int,
        step: ExecutionStep,
    ) -> dict[str, Any]:
        key = idempotency_key(task_id, plan_version, step)
        async with self._sessions() as session:
            existing = await session.scalar(select(ToolCall).where(ToolCall.idempotency_key == key))
            if existing is not None:
                if existing.status == "succeeded" and existing.result is not None:
                    return existing.result
                raise RuntimeError("tool call has uncertain or failed prior state")
            step_record = await session.scalar(
                select(ExecutionStepRecord)
                .join(ExecutionPlanRecord)
                .where(
                    ExecutionPlanRecord.task_id == task_id,
                    ExecutionPlanRecord.version == plan_version,
                    ExecutionStepRecord.step_key == step.step_id,
                )
            )
            if step_record is None:
                raise RuntimeError("execution step record is missing")
            call = ToolCall(
                task_id=task_id,
                step_id=step_record.id,
                tool_name=step.tool_name,
                idempotency_key=key,
                status="started",
                arguments=step.arguments,
            )
            session.add(call)
            step_record.status = "running"
            await session.commit()

        execution = await self._executor.execute(task_id, plan_version, step)
        result = execution.output.model_dump(mode="json")
        async with self._sessions() as session:
            call = await session.scalar(select(ToolCall).where(ToolCall.idempotency_key == key).with_for_update())
            if call is None:
                raise RuntimeError("tool call record disappeared")
            step_record = await session.get(ExecutionStepRecord, call.step_id)
            call.status = "succeeded"
            call.result = result
            if step_record is not None:
                step_record.status = "succeeded"
            evidence = execution.evidence
            session.add(
                EvidenceRecordModel(
                    id=evidence.evidence_id,
                    task_id=task_id,
                    step_id=call.step_id,
                    kind=evidence.kind,
                    content=evidence.model_dump(mode="json"),
                    sha256=evidence.sha256,
                )
            )
            await session.commit()
        return evidence.model_dump(mode="json")
