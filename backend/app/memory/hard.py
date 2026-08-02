import logging
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.contracts import HardMemoryItem, HardMemoryValue
from app.memory.models import HardMemoryItemModel
from app.memory.policy import validate_hard_memory_value
from app.memory.repositories import MemoryRepository
from app.models import AuditEvent

logger = logging.getLogger(__name__)


class HardMemoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = MemoryRepository(session)

    async def list(self, owner_id: str) -> tuple[HardMemoryItem, ...]:
        profile = await self._repository.profile(owner_id)
        if profile is None:
            return ()
        result: list[HardMemoryItem] = []
        for row in await self._repository.active_hard_items(profile.id):
            try:
                value, _ = validate_hard_memory_value(
                    row.namespace,
                    row.key,
                    row.value,
                    row.source_type,  # type: ignore[arg-type]
                )
                result.append(self._to_contract(row, value))
            except (TypeError, ValueError):
                logger.warning("invalid_hard_memory_item", extra={"memory_id": str(row.id)})
        return tuple(result)

    async def upsert(self, owner_id: str, value: HardMemoryValue) -> HardMemoryItem:
        validated, value_type = validate_hard_memory_value(
            value.namespace, value.key, value.value, value.source_type
        )
        profile = await self._repository.profile(owner_id, create=True)
        assert profile is not None
        current = await self._repository.active_hard_item(profile.id, value.namespace, value.key)
        if current is not None and current.value == validated:
            return self._to_contract(current, validated)
        revision = 1
        if current is not None:
            revision = current.revision + 1
            current.status = "superseded"
        row = HardMemoryItemModel(
            profile_id=profile.id,
            namespace=value.namespace,
            key=value.key,
            value=validated,
            value_type=value_type,
            source_type=value.source_type,
            source_message_id=value.source_message_id,
            revision=revision,
            status="active",
        )
        self._session.add(row)
        self._session.add(
            AuditEvent(
                trace_id=uuid4(),
                event_type="hard_memory_upserted",
                payload={
                    "memory_id": str(row.id),
                    "owner_id": owner_id,
                    "namespace": value.namespace,
                    "key": value.key,
                    "revision": revision,
                    "source_type": value.source_type,
                },
            )
        )
        profile.revision += 1
        await self._session.commit()
        await self._session.refresh(row)
        return self._to_contract(row, validated)

    async def delete(self, owner_id: str, memory_id: UUID) -> bool:
        profile = await self._repository.profile(owner_id)
        if profile is None:
            return False
        rows = await self._repository.active_hard_items(profile.id)
        row = next((item for item in rows if item.id == memory_id), None)
        if row is None:
            return False
        row.status = "deleted"
        self._session.add(
            AuditEvent(
                trace_id=uuid4(),
                event_type="hard_memory_deleted",
                payload={"memory_id": str(row.id), "owner_id": owner_id},
            )
        )
        profile.revision += 1
        await self._session.commit()
        return True

    @staticmethod
    def _to_contract(row: HardMemoryItemModel, value: Any) -> HardMemoryItem:
        return HardMemoryItem(
            id=row.id,
            namespace=row.namespace,
            key=row.key,
            value=value,
            source_type=row.source_type,
            source_message_id=row.source_message_id,
            revision=row.revision,
            status=row.status,
            created_at=row.created_at,
        )
