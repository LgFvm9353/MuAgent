from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.contracts.base import ContractModel

MemoryStatus = Literal["candidate", "active", "deprecated", "rejected", "deleted"]


class HardMemoryValue(ContractModel):
    namespace: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    key: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_.]*$")
    value: Any
    source_type: Literal["settings_ui", "explicit_user", "confirmed_candidate"]
    source_message_id: int | None = None


class HardMemoryItem(HardMemoryValue):
    id: UUID
    revision: int
    status: Literal["active", "superseded", "deleted"]
    created_at: datetime


class EnvironmentSource(ContractModel):
    path: str
    kind: str
    sha256: str
    content: dict[str, Any] | str


class EnvironmentSnapshot(ContractModel):
    workspace_root: str
    git_branch: str | None = None
    git_commit: str | None = None
    dirty: bool | None = None
    sources: tuple[EnvironmentSource, ...] = ()
    warnings: tuple[str, ...] = ()
    snapshot_hash: str


class EpisodicMemoryQuery(ContractModel):
    text: str = Field(default="", max_length=4_000)
    scope_id: str | None = Field(default=None, max_length=255)
    memory_types: tuple[str, ...] = ()
    facets: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    limit: int = Field(default=5, ge=1, le=20)


class EpisodicMemoryStatusUpdate(ContractModel):
    status: Literal["candidate", "active", "deprecated", "rejected"]


class EpisodicMemoryResult(ContractModel):
    id: UUID
    memory_type: str
    title: str
    problem: str
    resolution: str
    applicability: dict[str, Any]
    score: float
    score_breakdown: dict[str, float]
    warning: str = "Historical experience; verify against the current environment."


class MemoryContextBundle(ContractModel):
    hard_memory: tuple[HardMemoryItem, ...] = ()
    environment: EnvironmentSnapshot | None = None
    episodic_memories: tuple[EpisodicMemoryResult, ...] = ()
    warnings: tuple[str, ...] = ()

    @classmethod
    def empty(cls) -> "MemoryContextBundle":
        return cls()
