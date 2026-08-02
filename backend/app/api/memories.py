from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import database_session
from app.config import Settings
from app.memory.contracts import (
    EnvironmentSnapshot,
    EpisodicMemoryQuery,
    EpisodicMemoryResult,
    EpisodicMemoryStatusUpdate,
    HardMemoryItem,
    HardMemoryValue,
)
from app.memory.episodic import EpisodicMemoryService
from app.memory.hard import HardMemoryService
from app.memory.models import EpisodicMemoryModel

router = APIRouter(prefix="/memories", tags=["memories"])


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


Session = Annotated[AsyncSession, Depends(database_session)]
MemorySettings = Annotated[Settings, Depends(_settings)]


@router.get("/capabilities")
async def capabilities(settings: MemorySettings) -> dict[str, object]:
    return {
        "enabled": settings.memory_enabled,
        "layers": {
            "hard": settings.memory_hard_enabled,
            "environment": settings.memory_environment_enabled,
            "episodic": settings.memory_episodic_enabled,
        },
        "auto_consolidation": settings.memory_auto_consolidation_enabled,
    }


@router.get("/hard", response_model=list[HardMemoryItem])
async def list_hard_memories(
    settings: MemorySettings,
    session: Session,
) -> tuple[HardMemoryItem, ...]:
    return await HardMemoryService(session).list(settings.memory_default_owner_id)


@router.put("/hard", response_model=HardMemoryItem)
async def upsert_hard_memory(
    payload: HardMemoryValue,
    settings: MemorySettings,
    session: Session,
) -> HardMemoryItem:
    try:
        return await HardMemoryService(session).upsert(settings.memory_default_owner_id, payload)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error


@router.delete("/hard/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hard_memory(
    memory_id: UUID,
    settings: MemorySettings,
    session: Session,
) -> None:
    deleted = await HardMemoryService(session).delete(settings.memory_default_owner_id, memory_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="memory_not_found")


@router.get("/environment")
async def environment_snapshot(request: Request) -> EnvironmentSnapshot:
    return cast(EnvironmentSnapshot, await request.app.state.memory_service.environment_snapshot())


@router.post("/episodic/search")
async def search_episodic_memories(
    query: EpisodicMemoryQuery,
    settings: MemorySettings,
    session: Session,
) -> tuple[EpisodicMemoryResult, ...]:
    return await EpisodicMemoryService(
        session, minimum_score=settings.memory_min_retrieval_score
    ).search(settings.memory_default_owner_id, query)


@router.patch("/episodic/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_episodic_memory_status(
    memory_id: UUID,
    payload: EpisodicMemoryStatusUpdate,
    settings: MemorySettings,
    session: Session,
) -> None:
    memory = await _owned_episodic_memory(memory_id, settings, session)
    memory.status = payload.status
    await session.commit()


@router.delete("/episodic/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_episodic_memory(
    memory_id: UUID,
    settings: MemorySettings,
    session: Session,
) -> None:
    memory = await _owned_episodic_memory(memory_id, settings, session)
    memory.status = "deleted"
    await session.commit()


async def _owned_episodic_memory(
    memory_id: UUID, settings: Settings, session: AsyncSession
) -> EpisodicMemoryModel:
    memory = await session.scalar(
        select(EpisodicMemoryModel).where(
            EpisodicMemoryModel.id == memory_id,
            EpisodicMemoryModel.owner_id == settings.memory_default_owner_id,
        )
    )
    if memory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="memory_not_found")
    return memory
