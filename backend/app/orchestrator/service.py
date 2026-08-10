from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.runtime import AgentRuntime
from app.contracts.agents import VerificationReport
from app.contracts.execution import ExecutionPlan
from app.contracts.task import TaskContract
from app.harness.pricing import estimate_cost
from app.harness.registry import AgentRegistry
from app.harness.validation import validate_plan
from app.models import (
    AgentRun,
    EvidenceRecordModel,
    ExecutionPlanRecord,
    ExecutionStepRecord,
    UsageRecord,
    VerificationReportModel,
)
from app.orchestrator.state_machine import TaskState
from app.repositories import TaskRepository
from app.tools.registry import ToolRegistry


class OrchestratorService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        runtime: AgentRuntime,
        agents: AgentRegistry,
        tools: ToolRegistry,
    ) -> None:
        self._sessions = sessions
        self._runtime = runtime
        self._agents = agents
        self._tools = tools

    async def run(
        self,
        task_id: UUID,
        workspace_files: frozenset[str] = frozenset(),
    ) -> None:
        async with self._sessions() as session:
            repository = TaskRepository(session)
            task = await repository.get(task_id)
            contract = TaskContract.model_validate(task.contract)
            if task.cancel_requested:
                await repository.transition(
                    task_id,
                    TaskState.CANCELLED,
                    expected_version=task.version,
                    trace_id=task.trace_id,
                    reason="cancellation requested before orchestration",
                )
                await session.commit()
                return
            await repository.transition(
                task_id,
                TaskState.ANALYZING,
                expected_version=task.version,
                trace_id=task.trace_id,
                reason="starting Supervisor decomposition",
            )
            await session.commit()

        # All model-driven task decisions are owned by the Supervisor. It may
        # call specialist profiles through ``subagent`` when useful, but there
        # is no fixed specialist chain.
        plan_model = await self._runtime.supervisor_plan(contract, workspace_files)

        async with self._sessions() as session:
            repository = TaskRepository(session)
            task = await repository.get(task_id, for_update=True)
            invocations = self._runtime.drain_invocations()
            total_tokens = 0
            total_cost = 0.0
            for invocation in invocations:
                definition = self._agents.get(invocation.agent_id)
                run = AgentRun(
                    task_id=task_id,
                    agent_id=invocation.agent_id,
                    prompt_version=definition.prompt_version,
                    schema_version=definition.schema_version,
                    model=definition.model,
                    config_hash=definition.config_hash(invocation.phase),
                    status="succeeded",
                    output=invocation.output,
                )
                session.add(run)
                await session.flush()
                usage = invocation.usage
                estimated_cost = float(
                    estimate_cost(
                        usage.model,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        cache_creation_input_tokens=usage.cache_creation_input_tokens,
                        cache_read_input_tokens=usage.cache_read_input_tokens,
                    )
                )
                total_tokens += usage.total_input_tokens + usage.output_tokens
                total_cost += estimated_cost
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
                        estimated_cost_usd=estimated_cost,
                    )
                )
            if (
                total_tokens > contract.budget.max_tokens
                or total_cost > contract.budget.max_cost_usd
            ):
                await repository.transition(
                    task_id,
                    TaskState.BUDGET_EXCEEDED,
                    expected_version=task.version,
                    trace_id=task.trace_id,
                    reason="agent usage exceeded task budget",
                )
                await session.commit()
                return
            await repository.transition(
                task_id,
                TaskState.PLANNING,
                expected_version=task.version,
                trace_id=task.trace_id,
                reason="Supervisor decomposition completed",
            )
            await session.flush()
            task = await repository.get(task_id, for_update=True)
            validate_plan(
                plan_model,
                contract,
                self._tools,
                workspace_files=workspace_files,
            )
            plan_record = ExecutionPlanRecord(
                id=plan_model.plan_id,
                task_id=task_id,
                version=plan_model.version,
                content=plan_model.model_dump(mode="json"),
            )
            session.add(plan_record)
            for step in plan_model.steps:
                session.add(
                    ExecutionStepRecord(
                        plan_id=plan_record.id,
                        step_key=step.step_id,
                        status="pending",
                        content=step.model_dump(mode="json"),
                    )
                )
            await repository.transition(
                task_id,
                TaskState.POLICY_CHECK,
                expected_version=task.version,
                trace_id=task.trace_id,
                reason="plan passed deterministic validation",
            )
            await session.flush()
            task = await repository.get(task_id, for_update=True)
            await repository.transition(
                task_id,
                TaskState.EXECUTING,
                expected_version=task.version,
                trace_id=task.trace_id,
                reason=(
                    "execution plan accepted; Supervisor owns specialist decisions"
                ),
            )
            await session.commit()

    async def replan(
        self,
        task_id: UUID,
        workspace_files: frozenset[str],
    ) -> None:
        async with self._sessions() as session:
            repository = TaskRepository(session)
            task = await repository.get(task_id, for_update=True)
            if TaskState(task.state) is not TaskState.REPLANNING:
                raise RuntimeError("task is not waiting for replanning")
            contract = TaskContract.model_validate(task.contract)
            current_plan = await session.scalar(
                select(ExecutionPlanRecord)
                .where(ExecutionPlanRecord.task_id == task_id)
                .order_by(ExecutionPlanRecord.version.desc())
                .limit(1)
            )
            if current_plan is None:
                raise RuntimeError("replanning requires a prior plan")
            if current_plan.version >= 1 + contract.budget.max_revisions:
                await repository.transition(
                    task_id,
                    TaskState.NEEDS_REVIEW,
                    expected_version=task.version,
                    trace_id=task.trace_id,
                    reason="replanning limit reached",
                )
                await session.commit()
                return
            verification_record = await session.scalar(
                select(VerificationReportModel)
                .where(
                    VerificationReportModel.task_id == task_id,
                    VerificationReportModel.plan_id == current_plan.id,
                )
                .order_by(VerificationReportModel.created_at.desc())
                .limit(1)
            )
            if verification_record is None:
                raise RuntimeError("replanning requires a verification report")
            evidence_records = list(
                await session.scalars(
                    select(EvidenceRecordModel)
                    .where(EvidenceRecordModel.task_id == task_id)
                    .order_by(EvidenceRecordModel.created_at)
                )
            )
            prior_plan = ExecutionPlan.model_validate(current_plan.content)
            verification = VerificationReport.model_validate(verification_record.content)
            evidence = tuple(record.content for record in evidence_records)
            next_version = current_plan.version + 1

        new_plan = await self._runtime.supervisor_replan(
            contract,
            prior_plan,
            verification,
            evidence,
            workspace_files,
        )
        new_plan = new_plan.model_copy(update={"task_id": task_id, "version": next_version})
        validate_plan(
            new_plan,
            contract,
            self._tools,
            workspace_files=workspace_files,
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
                    config_hash=definition.config_hash(invocation.phase),
                    status="succeeded",
                    output=invocation.output,
                )
                session.add(run)
                await session.flush()
                usage = invocation.usage
                estimated_cost = float(
                    estimate_cost(
                        usage.model,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        cache_creation_input_tokens=usage.cache_creation_input_tokens,
                        cache_read_input_tokens=usage.cache_read_input_tokens,
                    )
                )
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
                        estimated_cost_usd=estimated_cost,
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
                await repository.transition(
                    task_id,
                    TaskState.BUDGET_EXCEEDED,
                    expected_version=task.version,
                    trace_id=task.trace_id,
                    reason="replanning exceeded task budget",
                )
                await session.commit()
                return
            plan_record = ExecutionPlanRecord(
                id=new_plan.plan_id,
                task_id=task_id,
                version=new_plan.version,
                content=new_plan.model_dump(mode="json"),
            )
            session.add(plan_record)
            for step in new_plan.steps:
                session.add(
                    ExecutionStepRecord(
                        plan_id=plan_record.id,
                        step_key=step.step_id,
                        status="pending",
                        content=step.model_dump(mode="json"),
                    )
                )
            await repository.transition(
                task_id,
                TaskState.POLICY_CHECK,
                expected_version=task.version,
                trace_id=task.trace_id,
                reason="replanned execution passed validation",
            )
            await session.flush()
            task = await repository.get(task_id, for_update=True)
            await repository.transition(
                task_id,
                TaskState.EXECUTING,
                expected_version=task.version,
                trace_id=task.trace_id,
                reason="replanned execution accepted; supervisor decisions remain agent-initiated",
            )
            await session.commit()
