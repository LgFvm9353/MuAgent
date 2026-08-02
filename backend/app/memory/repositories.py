from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.models import (
    EpisodicMemoryFacetModel,
    EpisodicMemoryModel,
    HardMemoryItemModel,
    MemoryProfileModel,
)


class MemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def profile(self, owner_id: str, *, create: bool = False) -> MemoryProfileModel | None:
        profile = await self._session.scalar(
            select(MemoryProfileModel)
            .where(MemoryProfileModel.owner_type == "user", MemoryProfileModel.owner_id == owner_id)
            .with_for_update()
        )
        if profile is None and create:
            profile = MemoryProfileModel(owner_type="user", owner_id=owner_id)
            self._session.add(profile)
            await self._session.flush()
        return profile

    async def active_hard_items(self, profile_id: UUID) -> tuple[HardMemoryItemModel, ...]:
        rows = await self._session.scalars(
            select(HardMemoryItemModel)
            .where(
                HardMemoryItemModel.profile_id == profile_id,
                HardMemoryItemModel.status == "active",
            )
            .order_by(HardMemoryItemModel.namespace, HardMemoryItemModel.key)
        )
        return tuple(rows)

    async def active_hard_item(
        self, profile_id: UUID, namespace: str, key: str
    ) -> HardMemoryItemModel | None:
        result: HardMemoryItemModel | None = await self._session.scalar(
            select(HardMemoryItemModel)
            .where(
                HardMemoryItemModel.profile_id == profile_id,
                HardMemoryItemModel.namespace == namespace,
                HardMemoryItemModel.key == key,
                HardMemoryItemModel.status == "active",
            )
            .with_for_update()
        )
        return result

    async def episodic_candidates(
        self,
        *,
        owner_id: str,
        scope_id: str | None,
        memory_types: tuple[str, ...],
        facets: dict[str, tuple[str, ...]],
        limit: int,
    ) -> tuple[tuple[EpisodicMemoryModel, set[tuple[str, str]]], ...]:
        now = datetime.now(UTC)
        statement = select(EpisodicMemoryModel).where(
            EpisodicMemoryModel.owner_id == owner_id,
            EpisodicMemoryModel.status == "active",
            or_(EpisodicMemoryModel.expires_at.is_(None), EpisodicMemoryModel.expires_at > now),
        )
        if scope_id is not None:
            statement = statement.where(
                or_(
                    EpisodicMemoryModel.scope_id == scope_id, EpisodicMemoryModel.scope_id.is_(None)
                )
            )
        if memory_types:
            statement = statement.where(EpisodicMemoryModel.memory_type.in_(memory_types))
        memories = tuple(await self._session.scalars(statement.limit(max(limit * 10, 50))))
        if not memories:
            return ()
        ids = [item.id for item in memories]
        facet_rows = await self._session.execute(
            select(
                EpisodicMemoryFacetModel.memory_id,
                EpisodicMemoryFacetModel.facet_type,
                EpisodicMemoryFacetModel.normalized_value,
            ).where(EpisodicMemoryFacetModel.memory_id.in_(ids))
        )
        by_memory: dict[UUID, set[tuple[str, str]]] = {item.id: set() for item in memories}
        for memory_id, facet_type, normalized in facet_rows:
            by_memory[memory_id].add((facet_type, normalized))
        requested = {
            (facet_type, value.strip().casefold())
            for facet_type, values in facets.items()
            for value in values
            if value.strip()
        }
        return tuple(
            (item, by_memory[item.id])
            for item in memories
            if not requested or requested.intersection(by_memory[item.id])
        )
