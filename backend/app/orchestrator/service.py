from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.task import TaskContract
from app.harness.pricing import estimate_cost
from app.harness.registry import AgentRegistry
from app.harness.validation import validate_plan
from app.models import (
    AgentRun,
    Decision,
    DeliberationRound,
    ExecutionPlanRecord,
    ExecutionStepRecord,
    Proposal,
    UsageRecord,
)
from app.orchestrator.scheduler import AgentRuntime, Scheduler
from app.orchestrator.state_machine import TaskState
from app.repositories import TaskRepository
from app.tools.policy import ToolPolicy
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
        self._scheduler = Scheduler(runtime)

    async def run(self, task_id: UUID) -> None:
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
                reason="starting parallel analysis",
            )
            await session.commit()

        result = await self._scheduler.deliberate(contract)

        async with self._sessions() as session:
            repository = TaskRepository(session)
            task = await repository.get(task_id, for_update=True)
            session.add(
                DeliberationRound(
                    task_id=task_id,
                    round_number=1,
                    new_information=True,
                )
            )
            invocations = self._runtime.drain_invocations()
            proposal_by_agent = dict(zip(("analyst", "domain_expert"), result.proposals, strict=True))
            for invocation in invocations:
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
                proposal = proposal_by_agent.get(invocation.agent_id)
                if proposal is not None:
                    session.add(
                        Proposal(
                            task_id=task_id,
                            agent_run_id=run.id,
                            version=1,
                            content=proposal.model_dump(mode="json"),
                        )
                    )
            await repository.transition(
                task_id,
                TaskState.DECIDING,
                expected_version=task.version,
                trace_id=task.trace_id,
                reason="analysis and critique completed",
            )
            await session.flush()
            task = await repository.get(task_id, for_update=True)
            decision = Decision(
                task_id=task_id,
                version=1,
                content=result.decision.model_dump(mode="json"),
            )
            session.add(decision)
            await session.flush()
            await repository.transition(
                task_id,
                TaskState.PLANNING,
                expected_version=task.version,
                trace_id=task.trace_id,
                reason="judge approved planning",
            )
            await session.flush()
            task = await repository.get(task_id, for_update=True)
            validate_plan(result.plan, contract, self._tools)
            plan = ExecutionPlanRecord(
                id=result.plan.plan_id,
                task_id=task_id,
                version=result.plan.version,
                decision_id=decision.id,
                content=result.plan.model_dump(mode="json"),
            )
            session.add(plan)
            for step in result.plan.steps:
                session.add(
                    ExecutionStepRecord(
                        plan_id=plan.id,
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
            confirmations = ToolPolicy(self._tools).confirmations(result.plan)
            target = TaskState.WAITING_CONFIRMATION if confirmations else TaskState.EXECUTING
            await repository.transition(
                task_id,
                target,
                expected_version=task.version,
                trace_id=task.trace_id,
                reason="high-risk confirmation required" if confirmations else "tool policy approved",
            )
            await session.commit()
