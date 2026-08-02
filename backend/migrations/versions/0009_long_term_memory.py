"""Add three-layer long-term memory storage.

Revision ID: 0009_long_term_memory
Revises: 0008_context_summaries
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_long_term_memory"
down_revision: str | None = "0008_context_summaries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE_OPTIONS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade() -> None:
    op.create_table(
        "memory_profiles",
        sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("owner_type", sa.String(32), nullable=False),
        sa.Column("owner_id", sa.String(100), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_type", "owner_id"),
        **_TABLE_OPTIONS,
    )
    op.create_table(
        "hard_memory_items",
        sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("profile_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("value_type", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_message_id", sa.BigInteger(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["memory_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "namespace", "key", "revision"),
        **_TABLE_OPTIONS,
    )
    op.create_index("ix_hard_memory_items_profile_id", "hard_memory_items", ["profile_id"])
    op.create_index(
        "ix_hard_memory_active", "hard_memory_items", ["profile_id", "status", "namespace", "key"]
    )
    op.create_table(
        "episodic_memories",
        sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("owner_id", sa.String(100), nullable=False),
        sa.Column("scope_type", sa.String(32), nullable=False),
        sa.Column("scope_id", sa.String(255), nullable=True),
        sa.Column("memory_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("problem_text", sa.Text(), nullable=False),
        sa.Column("resolution_text", sa.Text(), nullable=False),
        sa.Column("lessons_text", sa.Text(), nullable=True),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("applicability", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("validation_count", sa.Integer(), nullable=False),
        sa.Column("contradiction_count", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source_task_id", sa.Uuid(native_uuid=False), nullable=True),
        sa.Column("source_conversation_id", sa.Uuid(native_uuid=False), nullable=True),
        sa.Column("source_verification_id", sa.Uuid(native_uuid=False), nullable=True),
        sa.Column("environment_fingerprint", sa.String(64), nullable=True),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["source_conversation_id"], ["conversations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_verification_id"], ["verification_reports.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "scope_type", "scope_id", "content_hash"),
        **_TABLE_OPTIONS,
    )
    for name, columns in (
        ("ix_episodic_memories_owner_id", ["owner_id"]),
        ("ix_episodic_memories_scope_id", ["scope_id"]),
        ("ix_episodic_memories_memory_type", ["memory_type"]),
        ("ix_episodic_memories_status", ["status"]),
        ("ix_episodic_memories_source_task_id", ["source_task_id"]),
        ("ix_episodic_memories_source_conversation_id", ["source_conversation_id"]),
        ("ix_episodic_memories_source_verification_id", ["source_verification_id"]),
        ("ix_episodic_memories_environment_fingerprint", ["environment_fingerprint"]),
        ("ix_episodic_memories_expires_at", ["expires_at"]),
        ("ix_episodic_lookup", ["owner_id", "status", "scope_type", "scope_id"]),
    ):
        op.create_index(name, "episodic_memories", columns)
    op.create_table(
        "episodic_memory_facets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("memory_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("facet_type", sa.String(32), nullable=False),
        sa.Column("facet_value", sa.String(500), nullable=False),
        sa.Column("normalized_value", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["memory_id"], ["episodic_memories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("memory_id", "facet_type", "normalized_value"),
        **_TABLE_OPTIONS,
    )
    op.create_index("ix_episodic_memory_facets_memory_id", "episodic_memory_facets", ["memory_id"])
    op.create_index(
        "ix_episodic_facet_lookup",
        "episodic_memory_facets",
        ["facet_type", "normalized_value", "memory_id"],
    )
    op.create_table(
        "episodic_memory_sources",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("memory_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(100), nullable=False),
        sa.Column("relation", sa.String(32), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["memory_id"], ["episodic_memories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("memory_id", "source_type", "source_id", "relation"),
        **_TABLE_OPTIONS,
    )
    op.create_index(
        "ix_episodic_memory_sources_memory_id", "episodic_memory_sources", ["memory_id"]
    )
    op.create_table(
        "memory_consolidation_jobs",
        sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("task_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("dedup_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_type", sa.String(100), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_activate", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedup_key"),
        **_TABLE_OPTIONS,
    )
    op.create_index(
        "ix_memory_consolidation_jobs_task_id", "memory_consolidation_jobs", ["task_id"]
    )
    op.create_index("ix_memory_consolidation_jobs_status", "memory_consolidation_jobs", ["status"])
    op.create_index(
        "ix_memory_consolidation_jobs_lease_expires_at",
        "memory_consolidation_jobs",
        ["lease_expires_at"],
    )
    op.create_index(
        "ix_memory_consolidation_jobs_available_at", "memory_consolidation_jobs", ["available_at"]
    )

    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        op.execute(
            "CREATE FULLTEXT INDEX ft_episodic_search ON episodic_memories "
            "(title, problem_text, resolution_text, search_text) WITH PARSER ngram"
        )


def downgrade() -> None:
    op.drop_table("memory_consolidation_jobs")
    op.drop_table("episodic_memory_sources")
    op.drop_table("episodic_memory_facets")
    op.drop_table("episodic_memories")
    op.drop_table("hard_memory_items")
    op.drop_table("memory_profiles")
