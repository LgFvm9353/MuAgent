from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.contracts.task import AcceptanceCriterion, BudgetLimits, TaskContract
from app.models import (
    AgentInvocationQueueEntry,
    AgentRun,
    ConversationMessage,
    ConversationTurn,
    Task,
)
from app.repositories import TaskRepository
from app.tools.factory import DEFAULT_LOCAL_TOOL_NAMES


@dataclass(frozen=True, slots=True)
class MentionExecutionResult:
    task_id: UUID
    created: bool


class MentionExecutionService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def create_task(
        self,
        entry: AgentInvocationQueueEntry,
        run: AgentRun,
    ) -> MentionExecutionResult:
        if entry.intent != "execute" or entry.target_agent_id != "architect":
            raise ValueError("only execute handoffs to architect can create controlled tasks")
        existing = await self._session.scalar(
            select(Task).where(Task.originating_invocation_id == entry.id).with_for_update()
        )
        if existing is not None:
            return MentionExecutionResult(existing.id, False)

        goal = entry.objective.strip()
        if not goal:
            raise ValueError("execution objective must not be empty")
        task_id = uuid4()
        allowed_tools = self._settings.mention_execution_tool_set & DEFAULT_LOCAL_TOOL_NAMES
        if not allowed_tools:
            raise ValueError("mention execution tool allowlist is empty")
        contract = TaskContract(
            task_id=task_id,
            goal=goal[:10_000],
            inputs={
                "conversation_id": str(entry.conversation_id),
                "turn_id": str(entry.turn_id),
                "source_message_id": str(entry.source_message_id or ""),
            },
            constraints=(
                "Only use server-authorized tools and stay inside the task workspace.",
                "High-risk operations require immutable user confirmation before execution.",
            ),
            acceptance_criteria=(
                AcceptanceCriterion(
                    description="The approved plan completes and independent verification passes.",
                    verification_method="Inspect persisted tool evidence and verifier report.",
                ),
            ),
            allowed_tools=allowed_tools,
            budget=BudgetLimits(),
            failure_policy="Stop on unsafe or unverifiable execution and request review.",
        )
        task = Task(
            id=task_id,
            conversation_id=entry.conversation_id,
            originating_invocation_id=entry.id,
            trace_id=uuid4(),
            contract=contract.model_dump(mode="json"),
        )
        await TaskRepository(self._session).add(task)
        await self._session.flush()
        entry.task_id = task.id
        run.task_id = task.id
        turn = await self._session.get(ConversationTurn, entry.turn_id)
        if turn is not None:
            turn.task_id = task.id
            turn.requires_execution = True
            turn.status = "executing"
        self._session.add(
            ConversationMessage(
                task_id=task.id,
                conversation_id=entry.conversation_id,
                turn_id=entry.turn_id,
                agent_run_id=run.id,
                handoff_id=entry.handoff_id,
                reply_to_message_id=entry.source_message_id,
                agent_id="architect",
                role="system",
                message_type="execution_requested",
                phase="planning",
                summary="执行请求已进入受控计划与审批流程。",
                content={
                    "task_id": str(task.id),
                    "objective": goal,
                    "allowed_tools": sorted(allowed_tools),
                    "state": task.state,
                },
                source_id=f"mention-execution:{entry.id}",
            )
        )
        return MentionExecutionResult(task.id, True)
