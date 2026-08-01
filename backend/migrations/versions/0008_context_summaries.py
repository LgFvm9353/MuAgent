"""Add rolling conversation context summaries.

Revision ID: 0008_context_summaries
Revises: 0007_remove_handoff_runtime
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_context_summaries"
down_revision: str | None = "0007_remove_handoff_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_context_summaries",
        sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("conversation_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("parent_summary_id", sa.Uuid(native_uuid=False), nullable=True),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_message_start_id", sa.BigInteger(), nullable=False),
        sa.Column("source_message_end_id", sa.BigInteger(), nullable=False),
        sa.Column("covered_message_count", sa.Integer(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("key_message_ids", sa.JSON(), nullable=False),
        sa.Column("source_token_count", sa.Integer(), nullable=False),
        sa.Column("summary_token_count", sa.Integer(), nullable=False),
        sa.Column("compression_model", sa.String(100), nullable=False),
        sa.Column("tokenizer", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_summary_id"], ["conversation_context_summaries.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_context_summary_current",
        "conversation_context_summaries",
        ["conversation_id", "status", "created_at"],
    )
    op.create_index(
        "ix_conversation_context_summaries_conversation_id",
        "conversation_context_summaries",
        ["conversation_id"],
    )
    op.create_index(
        "ix_conversation_context_summaries_status",
        "conversation_context_summaries",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("conversation_context_summaries")
