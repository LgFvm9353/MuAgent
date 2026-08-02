import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.memory.contracts import (
    EnvironmentSnapshot,
    EpisodicMemoryQuery,
    EpisodicMemoryResult,
    HardMemoryItem,
    MemoryContextBundle,
)
from app.memory.environment import EnvironmentMemoryService
from app.memory.episodic import EpisodicMemoryService
from app.memory.hard import HardMemoryService

logger = logging.getLogger(__name__)


class MemoryService:
    def __init__(self, settings: Settings, workspace_root: Path) -> None:
        self._settings = settings
        self._environment = EnvironmentMemoryService(
            workspace_root, max_file_bytes=settings.memory_environment_max_file_bytes
        )

    async def context(
        self,
        session: AsyncSession,
        *,
        user_text: str,
        scope_id: str | None = None,
    ) -> MemoryContextBundle:
        if not self._settings.memory_enabled:
            return MemoryContextBundle.empty()
        hard_memory: tuple[HardMemoryItem, ...] = ()
        environment: EnvironmentSnapshot | None = None
        episodic_memories: tuple[EpisodicMemoryResult, ...] = ()
        warnings: list[str] = []
        if self._settings.memory_hard_enabled:
            try:
                hard_memory = await HardMemoryService(session).list(
                    self._settings.memory_default_owner_id
                )
            except Exception:
                logger.exception("hard_memory_load_failed")
                warnings.append("hard_memory_unavailable")
        if self._settings.memory_environment_enabled:
            try:
                environment = await self._environment.snapshot()
            except Exception:
                logger.exception("environment_memory_load_failed")
                warnings.append("environment_memory_unavailable")
        if self._settings.memory_episodic_enabled:
            try:
                episodic_memories = await EpisodicMemoryService(
                    session, minimum_score=self._settings.memory_min_retrieval_score
                ).search(
                    self._settings.memory_default_owner_id,
                    EpisodicMemoryQuery(
                        text=user_text,
                        scope_id=scope_id,
                        limit=self._settings.memory_max_context_items,
                    ),
                )
            except Exception:
                logger.exception("episodic_memory_load_failed")
                warnings.append("episodic_memory_unavailable")
        bundle = MemoryContextBundle(
            hard_memory=hard_memory,
            environment=environment,
            episodic_memories=episodic_memories,
            warnings=tuple(warnings),
        )
        return self._trim(bundle)

    def _trim(self, bundle: MemoryContextBundle) -> MemoryContextBundle:
        max_characters = self._settings.memory_max_context_tokens * 4
        if len(bundle.model_dump_json()) <= max_characters:
            return bundle
        episodic = list(bundle.episodic_memories)
        while episodic:
            episodic.pop()
            candidate = bundle.model_copy(update={"episodic_memories": tuple(episodic)})
            if len(candidate.model_dump_json()) <= max_characters:
                return candidate
        environment = bundle.environment
        if environment is not None:
            sources = list(environment.sources)
            while sources:
                sources.pop()
                trimmed_environment = environment.model_copy(update={"sources": tuple(sources)})
                candidate = bundle.model_copy(
                    update={"episodic_memories": (), "environment": trimmed_environment}
                )
                if len(candidate.model_dump_json()) <= max_characters:
                    return candidate
        return bundle.model_copy(
            update={
                "episodic_memories": (),
                "environment": None,
                "warnings": (*bundle.warnings, "memory_context_budget_exceeded"),
            }
        )

    async def environment_snapshot(self) -> EnvironmentSnapshot:
        return await self._environment.snapshot()
