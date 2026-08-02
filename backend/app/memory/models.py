from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, TimestampMixin


class MemoryProfileModel(Base, TimestampMixin):
    __tablename__ = "memory_profiles"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    owner_type: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    owner_id: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    __table_args__ = (
        UniqueConstraint("owner_type", "owner_id"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )


class HardMemoryItemModel(Base, TimestampMixin):
    __tablename__ = "hard_memory_items"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("memory_profiles.id", ondelete="CASCADE"), index=True
    )
    namespace: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    value_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_message_id: Mapped[int | None] = mapped_column(BigInteger)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    __table_args__ = (
        UniqueConstraint("profile_id", "namespace", "key", "revision"),
        Index("ix_hard_memory_active", "profile_id", "status", "namespace", "key"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )


class EpisodicMemoryModel(Base, TimestampMixin):
    __tablename__ = "episodic_memories"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    owner_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_id: Mapped[str | None] = mapped_column(String(255), index=True)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="candidate", index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    problem_text: Mapped[str] = mapped_column(Text, nullable=False)
    resolution_text: Mapped[str] = mapped_column(Text, nullable=False)
    lessons_text: Mapped[str | None] = mapped_column(Text)
    search_text: Mapped[str] = mapped_column(Text, nullable=False)
    applicability: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    validation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    contradiction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), index=True
    )
    source_conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    source_verification_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("verification_reports.id", ondelete="SET NULL"), index=True
    )
    environment_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    __table_args__ = (
        UniqueConstraint("owner_id", "scope_type", "scope_id", "content_hash"),
        Index("ix_episodic_lookup", "owner_id", "status", "scope_type", "scope_id"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )


class EpisodicMemoryFacetModel(Base, TimestampMixin):
    __tablename__ = "episodic_memory_facets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    memory_id: Mapped[UUID] = mapped_column(
        ForeignKey("episodic_memories.id", ondelete="CASCADE"), index=True
    )
    facet_type: Mapped[str] = mapped_column(String(32), nullable=False)
    facet_value: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(500), nullable=False)
    __table_args__ = (
        UniqueConstraint("memory_id", "facet_type", "normalized_value"),
        Index("ix_episodic_facet_lookup", "facet_type", "normalized_value", "memory_id"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )


class EpisodicMemorySourceModel(Base, TimestampMixin):
    __tablename__ = "episodic_memory_sources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    memory_id: Mapped[UUID] = mapped_column(
        ForeignKey("episodic_memories.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    relation: Mapped[str] = mapped_column(String(32), nullable=False)
    source_hash: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("memory_id", "source_type", "source_id", "relation"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )


class MemoryConsolidationJobModel(Base, TimestampMixin):
    __tablename__ = "memory_consolidation_jobs"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), index=True
    )
    error_type: Mapped[str | None] = mapped_column(String(100))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_activate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
