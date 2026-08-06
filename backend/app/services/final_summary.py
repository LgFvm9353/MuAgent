from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    EvidenceRecordModel,
    ExecutionPlanRecord,
    ExecutionStepRecord,
    Task,
    VerificationReportModel,
)


class FinalSummaryService:
    def __init__(
        self,
        session: AsyncSession,
        conversation_store: object | None = None,
    ) -> None:
        self._session = session
        self._conversation_store = conversation_store

    async def add(self, task: Task, *, reason: str) -> None:
        source_id = f"final-summary:{task.id}:{task.version}"
        if self._conversation_store is not None and await self._conversation_store.find_by_source(
            task.conversation_id, source_id
        ) is not None:
            return

        plan = await self._session.scalar(
            select(ExecutionPlanRecord)
            .where(ExecutionPlanRecord.task_id == task.id)
            .order_by(ExecutionPlanRecord.version.desc())
            .limit(1)
        )
        steps: list[ExecutionStepRecord] = []
        if plan is not None:
            steps = list(
                await self._session.scalars(
                    select(ExecutionStepRecord)
                    .where(ExecutionStepRecord.plan_id == plan.id)
                    .order_by(ExecutionStepRecord.created_at)
                )
            )
        evidence = list(
            await self._session.scalars(
                select(EvidenceRecordModel)
                .where(EvidenceRecordModel.task_id == task.id)
                .order_by(EvidenceRecordModel.created_at)
            )
        )
        verification = await self._session.scalar(
            select(VerificationReportModel)
            .where(VerificationReportModel.task_id == task.id)
            .order_by(VerificationReportModel.created_at.desc())
            .limit(1)
        )

        counts = {
            state: sum(step.status == state for step in steps)
            for state in ("succeeded", "failed", "skipped", "pending")
        }
        files = [
            {
                "path": record.content.get("artifact_path"),
                "sha256": record.sha256,
            }
            for record in evidence
            if record.kind == "file" and record.content.get("artifact_path")
        ]
        checks = [
            {
                "exit_code": record.content.get("exit_code"),
                "summary": record.content.get("summary", record.content.get("output")),
            }
            for record in evidence
            if record.kind == "check"
        ]
        verification_content: dict[str, Any] | None = (
            verification.content if verification is not None else None
        )
        goal = str(task.contract.get("goal", "任务"))
        status_text = {
            "SUCCEEDED": "已完成",
            "NEEDS_REVIEW": "需要人工处理",
            "FAILED": "执行失败",
            "CANCELLED": "已取消",
            "REJECTED": "已拒绝",
            "BUDGET_EXCEEDED": "已超过预算",
        }.get(task.state, task.state)
        summary = f"{status_text}：{goal}"[:1000]  # noqa: RUF001
        content = {
            "state": task.state,
            "goal": goal,
            "reason": reason,
            "step_counts": counts,
            "files": files,
            "checks": checks,
            "verification": verification_content,
            "next_action": (
                "可以在当前对话中继续提出修改要求。"
                if task.state == "SUCCEEDED"
                else "请查看失败证据，并在当前对话中补充要求或重新尝试。"  # noqa: RUF001
            ),
        }
        if self._conversation_store is not None:
            await self._conversation_store.append(
                task.conversation_id,
                task_id=task.id,
                agent_id="system",
                role="system",
                message_type="final_summary",
                phase="completion",
                summary=summary,
                content=content,
                source_id=source_id,
            )
