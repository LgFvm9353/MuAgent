import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.execution import ExecutionPlan, ExecutionStep
from app.contracts.task import TaskContract
from app.harness.pricing import estimate_cost
from app.harness.registry import AgentRegistry
from app.models import (
    AgentRun,
    ConversationMessage,
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
from app.workspace.artifacts import collect_text_artifacts
from app.workspace.paths import WorkspaceViolationError
from app.workspace.task_directory import WorkspacePreconditionError


@dataclass(frozen=True, slots=True)
class StepOutcome:
    evidence: dict[str, Any]
    succeeded: bool


class ExecutionService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        runtime: AgentRuntime,
        agents: AgentRegistry,
        executor: ToolExecutor,
        workspace_root: Path,
    ) -> None:
        self._sessions = sessions
        self._runtime = runtime
        self._agents = agents
        self._executor = executor
        self._workspace_root = workspace_root

    async def execute(self, task_id: UUID) -> None:
        contract, plan = await self._load(task_id)
        completed, evidence = await self._load_progress(task_id, plan)
        remaining = {step.step_id: step for step in plan.steps if step.step_id not in completed}
        failed_step: str | None = None
        while remaining and failed_step is None:
            ready = [step for step in remaining.values() if step.depends_on <= completed]
            if not ready:
                raise RuntimeError("execution plan has no runnable step")
            for step in ready:
                await self._check_cancelled(task_id)
                outcome = await self._execute_step(task_id, plan.version, step)
                evidence.append(outcome.evidence)
                remaining.pop(step.step_id)
                if outcome.succeeded:
                    completed.add(step.step_id)
                else:
                    failed_step = step.step_id
                    break

        async with self._sessions() as session:
            repository = TaskRepository(session)
            task = await repository.get(task_id, for_update=True)
            await repository.transition(
                task_id,
                TaskState.VERIFYING,
                expected_version=task.version,
                trace_id=task.trace_id,
                reason="execution check failed; validating evidence"
                if failed_step is not None
                else "all execution steps completed",
            )
            await session.commit()

        step_statuses = {
            step.step_id: (
                "failed"
                if step.step_id == failed_step
                else "succeeded"
                if step.step_id in completed
                else "skipped"
            )
            for step in plan.steps
        }
        execution_records = tuple(
            {
                "step_id": step.step_id,
                "tool_name": step.tool_name,
                "arguments": step.arguments,
                "expected_result": step.expected_result,
                "verification_method": step.verification_method,
                "status": step_statuses[step.step_id],
            }
            for step in plan.steps
        )
        artifacts = collect_text_artifacts(self._workspace_root)
        report = await self._runtime.verifier(
            contract,
            plan,
            execution_records,
            tuple(evidence),
            artifacts,
        )
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
            await session.flush()
            usage_totals = (
                await session.execute(
                    select(
                        func.coalesce(
                            func.sum(
                                UsageRecord.input_tokens
                                + UsageRecord.cache_creation_input_tokens
                                + UsageRecord.cache_read_input_tokens
                                + UsageRecord.output_tokens
                            ),
                            0,
                        ),
                        func.coalesce(func.sum(UsageRecord.estimated_cost_usd), 0.0),
                    ).where(UsageRecord.task_id == task_id)
                )
            ).one()
            if (
                int(usage_totals[0]) > contract.budget.max_tokens
                or float(usage_totals[1]) > contract.budget.max_cost_usd
            ):
                target = TaskState.BUDGET_EXCEEDED
                reason = "verification exceeded task budget"
            elif report.verdict == "failed" and report.recommendation == "replan":
                target = TaskState.REPLANNING
                reason = f"verifier verdict: {report.verdict}"
            else:
                target = {
                    "passed": TaskState.SUCCEEDED,
                    "failed": TaskState.FAILED,
                    "needs_review": TaskState.NEEDS_REVIEW,
                }[report.verdict]
                reason = f"verifier verdict: {report.verdict}"
            await repository.transition(
                task_id,
                target,
                expected_version=task.version,
                trace_id=task.trace_id,
                reason=reason,
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
            return TaskContract.model_validate(task.contract), ExecutionPlan.model_validate(
                plan_record.content
            )

    async def _load_progress(
        self,
        task_id: UUID,
        plan: ExecutionPlan,
    ) -> tuple[set[str], list[dict[str, Any]]]:
        async with self._sessions() as session:
            records = list(
                await session.scalars(
                    select(ExecutionStepRecord)
                    .join(ExecutionPlanRecord)
                    .where(ExecutionPlanRecord.id == plan.plan_id)
                )
            )
            completed = {record.step_key for record in records if record.status == "succeeded"}
            uncertain = [
                record.step_key for record in records if record.status in {"running", "failed"}
            ]
            if uncertain:
                raise RuntimeError(
                    "execution contains uncertain or failed steps requiring review: "
                    + ", ".join(sorted(uncertain))
                )
            record_ids = [record.id for record in records]
            evidence = (
                list(
                    await session.scalars(
                        select(EvidenceRecordModel)
                        .where(
                            EvidenceRecordModel.task_id == task_id,
                            EvidenceRecordModel.step_id.in_(record_ids),
                        )
                        .order_by(EvidenceRecordModel.created_at)
                    )
                )
                if record_ids
                else []
            )
            return completed, [item.content for item in evidence]

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
    ) -> StepOutcome:
        key = idempotency_key(task_id, plan_version, step)
        async with self._sessions() as session:
            existing = await session.scalar(select(ToolCall).where(ToolCall.idempotency_key == key))
            if existing is not None:
                if existing.status == "succeeded" and existing.result is not None:
                    return StepOutcome(existing.result, True)
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

        try:
            execution = await self._executor.execute(task_id, plan_version, step)
            evidence = execution.evidence
            if evidence.kind == "file" and evidence.artifact_path is not None:
                evidence_path = (self._workspace_root / evidence.artifact_path).resolve(strict=True)
                workspace_root = self._workspace_root.resolve(strict=True)
                if not evidence_path.is_relative_to(workspace_root) or not evidence_path.is_file():
                    raise WorkspaceViolationError("file evidence escaped the task workspace")
                actual_sha256 = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
                if actual_sha256 != evidence.sha256:
                    raise RuntimeError("file evidence hash does not match the workspace")
        except Exception as error:
            is_precondition = isinstance(
                error,
                (NotADirectoryError, WorkspaceViolationError),
            )
            async with self._sessions() as session:
                failed_call = await session.scalar(
                    select(ToolCall).where(ToolCall.idempotency_key == key).with_for_update()
                )
                if failed_call is not None:
                    failed_call.status = "failed"
                    failed_call.error_type = type(error).__name__
                    step_record = await session.get(ExecutionStepRecord, failed_call.step_id)
                    if step_record is not None:
                        step_record.status = "failed"
                    session.add(
                        ConversationMessage(
                            task_id=task_id,
                            agent_id="executor",
                            role="tool",
                            message_type="tool_failed",
                            phase="execution",
                            summary=f"{step.tool_name} 无法执行。项目状态不符合计划。"
                            if is_precondition
                            else f"{step.tool_name} 执行失败。",
                            content={
                                "step_id": step.step_id,
                                "tool_name": step.tool_name,
                                "risk": step.risk,
                                "error_code": type(error).__name__,
                                "action": "请检查任务文件及计划前置条件后重试。"
                                if is_precondition
                                else "请查看任务错误信息。",
                            },
                            source_id=f"tool-call-failed:{key}",
                        )
                    )
                    await session.commit()
            if is_precondition:
                raise WorkspacePreconditionError(
                    "workspace does not satisfy the execution plan"
                ) from error
            raise
        result = execution.output.model_dump(mode="json")
        evidence = execution.evidence
        check_failed = evidence.kind == "check" and evidence.exit_code != 0
        status = "failed" if check_failed else "succeeded"
        async with self._sessions() as session:
            completed_call = await session.scalar(
                select(ToolCall).where(ToolCall.idempotency_key == key).with_for_update()
            )
            if completed_call is None:
                raise RuntimeError("tool call record disappeared")
            step_record = await session.get(ExecutionStepRecord, completed_call.step_id)
            completed_call.status = status
            completed_call.result = result
            if check_failed:
                completed_call.error_type = "CheckFailed"
            if step_record is not None:
                step_record.status = status
            session.add(
                EvidenceRecordModel(
                    id=evidence.evidence_id,
                    task_id=task_id,
                    step_id=completed_call.step_id,
                    kind=evidence.kind,
                    content=evidence.model_dump(mode="json"),
                    sha256=evidence.sha256,
                )
            )
            session.add(
                ConversationMessage(
                    task_id=task_id,
                    agent_id="executor",
                    role="tool",
                    message_type="tool_failed" if check_failed else "tool_result",
                    phase="execution",
                    summary=f"{step.tool_name} 检查未通过，正在验证失败证据。"
                    if check_failed
                    else f"{step.tool_name} 执行完成。",
                    content={
                        "step_id": step.step_id,
                        "tool_name": step.tool_name,
                        "risk": step.risk,
                        "status": status,
                        "result": result,
                        "evidence": evidence.model_dump(mode="json"),
                    },
                    source_id=f"tool-call:{key}",
                )
            )
            await session.commit()
        return StepOutcome(evidence.model_dump(mode="json"), not check_failed)
