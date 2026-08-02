import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.episodic import normalize_facet
from app.memory.models import (
    EpisodicMemoryFacetModel,
    EpisodicMemoryModel,
    EpisodicMemorySourceModel,
    MemoryConsolidationJobModel,
)
from app.models import Task, VerificationReportModel
from app.redaction import redact


class MemoryConsolidationService:
    def __init__(self, session: AsyncSession, *, owner_id: str, retention_days: int) -> None:
        self._session = session
        self._owner_id = owner_id
        self._retention_days = retention_days

    async def enqueue(self, task_id: UUID, *, auto_activate: bool) -> UUID:
        dedup_key = hashlib.sha256(f"memory-consolidation:{task_id}".encode()).hexdigest()
        existing = await self._session.scalar(
            select(MemoryConsolidationJobModel).where(
                MemoryConsolidationJobModel.dedup_key == dedup_key
            )
        )
        if existing is not None:
            return existing.id
        job = MemoryConsolidationJobModel(
            task_id=task_id,
            dedup_key=dedup_key,
            status="pending",
            auto_activate=auto_activate,
        )
        self._session.add(job)
        await self._session.commit()
        return job.id

    async def process(self, job_id: UUID) -> UUID | None:
        job = await self._session.scalar(
            select(MemoryConsolidationJobModel)
            .where(MemoryConsolidationJobModel.id == job_id)
            .with_for_update()
        )
        if job is None:
            raise ValueError("consolidation_job_not_found")
        if job.status == "completed":
            return None
        job.status = "running"
        job.attempt += 1
        await self._session.flush()
        try:
            memory_id = await self._consolidate(job.task_id, auto_activate=job.auto_activate)
            job.status = "completed"
            job.completed_at = datetime.now(UTC)
            job.error_type = None
            await self._session.commit()
            return memory_id
        except Exception as error:
            job.status = "failed"
            job.error_type = type(error).__name__[:100]
            await self._session.commit()
            raise

    async def _consolidate(self, task_id: UUID, *, auto_activate: bool) -> UUID | None:
        task = await self._session.get(Task, task_id)
        if task is None:
            raise ValueError("task_not_found")
        verification = await self._session.scalar(
            select(VerificationReportModel)
            .where(VerificationReportModel.task_id == task_id)
            .order_by(VerificationReportModel.created_at.desc())
        )
        if verification is None:
            return None
        contract = redact(task.contract)
        report = redact(verification.content)
        accepted = verification.verdict.casefold() in {"passed", "success", "verified"}
        title = str(contract.get("goal", "Verified task experience"))[:500]
        problem = self._text(contract)
        resolution = self._text(report)
        canonical = json.dumps(
            {"task": contract, "verification": report}, sort_keys=True, ensure_ascii=True
        )
        content_hash = hashlib.sha256(canonical.encode()).hexdigest()
        existing = await self._session.scalar(
            select(EpisodicMemoryModel).where(
                EpisodicMemoryModel.owner_id == self._owner_id,
                EpisodicMemoryModel.scope_type == "project",
                EpisodicMemoryModel.scope_id == str(task.conversation_id),
                EpisodicMemoryModel.content_hash == content_hash,
            )
        )
        if existing is not None:
            existing.validation_count += int(accepted)
            if accepted:
                existing.last_validated_at = datetime.now(UTC)
            return existing.id
        memory = EpisodicMemoryModel(
            owner_id=self._owner_id,
            scope_type="project",
            scope_id=str(task.conversation_id),
            memory_type="task_outcome",
            status="active" if accepted and auto_activate else "candidate",
            title=title,
            problem_text=problem,
            resolution_text=resolution,
            search_text=f"{title} {problem} {resolution}",
            applicability={},
            confidence=1.0 if accepted else 0.5,
            validation_count=1 if accepted else 0,
            contradiction_count=0 if accepted else 1,
            content_hash=content_hash,
            source_task_id=task.id,
            source_conversation_id=task.conversation_id,
            source_verification_id=verification.id,
            last_validated_at=datetime.now(UTC) if accepted else None,
            expires_at=datetime.now(UTC) + timedelta(days=self._retention_days),
        )
        self._session.add(memory)
        await self._session.flush()
        self._session.add(
            EpisodicMemorySourceModel(
                memory_id=memory.id,
                source_type="verification_report",
                source_id=str(verification.id),
                relation="verified_by" if accepted else "derived_from",
            )
        )
        for facet_type, values in self._facets(contract).items():
            for value in values:
                self._session.add(
                    EpisodicMemoryFacetModel(
                        memory_id=memory.id,
                        facet_type=facet_type,
                        facet_value=value,
                        normalized_value=normalize_facet(value),
                    )
                )
        return memory.id

    @staticmethod
    def _text(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)[:16_000]

    @staticmethod
    def _facets(contract: dict[str, Any]) -> dict[str, tuple[str, ...]]:
        result: dict[str, tuple[str, ...]] = {}
        for key in ("languages", "frameworks", "tools", "error_codes"):
            value = contract.get(key)
            if isinstance(value, list):
                result[key.removesuffix("s")] = tuple(str(item)[:500] for item in value)
        return result
