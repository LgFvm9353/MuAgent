"""add mention-driven agent invocation queue

Revision ID: 0004_agent_invocation_queue
Revises: 0003_tool_governance
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_agent_invocation_queue"
down_revision: str | None = "0003_tool_governance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "agent_invocation_queue" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    with op.batch_alter_table("handoff_records") as batch:
        batch.add_column(
            sa.Column("intent", sa.String(32), nullable=False, server_default="delegate")
        )
        batch.alter_column("objective", existing_type=sa.String(1000), type_=sa.String(4000))
        batch.add_column(sa.Column("parent_handoff_id", sa.Uuid(native_uuid=False)))
        batch.add_column(sa.Column("completed_message_id", sa.BigInteger()))
        batch.add_column(sa.Column("depth", sa.Integer(), nullable=False, server_default="0"))
        batch.create_foreign_key(
            "fk_handoff_parent",
            "handoff_records",
            ["parent_handoff_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_handoff_completed_message",
            "conversation_messages",
            ["completed_message_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_handoff_records_parent_handoff_id", ["parent_handoff_id"])

    op.create_table(
        "agent_invocation_queue",
        sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("conversation_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("turn_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("task_id", sa.Uuid(native_uuid=False)),
        sa.Column("source_agent_id", sa.String(100)),
        sa.Column("target_agent_id", sa.String(100), nullable=False),
        sa.Column("source_message_id", sa.BigInteger()),
        sa.Column("handoff_id", sa.Uuid(native_uuid=False)),
        sa.Column("parent_invocation_id", sa.Uuid(native_uuid=False)),
        sa.Column("intent", sa.String(32), nullable=False),
        sa.Column("objective", sa.String(4000), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dedup_key", sa.String(64), nullable=False),
        sa.Column("lease_owner", sa.String(100)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_type", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["turn_id"], ["conversation_turns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_message_id"], ["conversation_messages.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["handoff_id"], ["handoff_records.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["parent_invocation_id"], ["agent_invocation_queue.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedup_key"),
        mysql_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_agent_invocation_queue_conversation_id", "agent_invocation_queue", ["conversation_id"]
    )
    op.create_index("ix_agent_invocation_queue_turn_id", "agent_invocation_queue", ["turn_id"])
    op.create_index("ix_agent_invocation_queue_task_id", "agent_invocation_queue", ["task_id"])
    op.create_index(
        "ix_agent_invocation_queue_handoff_id", "agent_invocation_queue", ["handoff_id"]
    )
    op.create_index(
        "ix_agent_invocation_queue_parent_invocation_id",
        "agent_invocation_queue",
        ["parent_invocation_id"],
    )
    op.create_index(
        "ix_invocation_queue_claim",
        "agent_invocation_queue",
        ["conversation_id", "target_agent_id", "status", "available_at"],
    )

    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("invocation_queue_entry_id", sa.Uuid(native_uuid=False)))
        batch.add_column(sa.Column("parent_run_id", sa.Uuid(native_uuid=False)))
        batch.add_column(sa.Column("intent", sa.String(32)))
        batch.create_foreign_key(
            "fk_agent_run_invocation",
            "agent_invocation_queue",
            ["invocation_queue_entry_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_agent_run_parent", "agent_runs", ["parent_run_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_unique_constraint(
            "uq_agent_runs_invocation_queue_entry_id", ["invocation_queue_entry_id"]
        )
        batch.create_index("ix_agent_runs_invocation_queue_entry_id", ["invocation_queue_entry_id"])
        batch.create_index("ix_agent_runs_parent_run_id", ["parent_run_id"])


def downgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_index("ix_agent_runs_parent_run_id")
        batch.drop_index("ix_agent_runs_invocation_queue_entry_id")
        batch.drop_constraint("uq_agent_runs_invocation_queue_entry_id", type_="unique")
        batch.drop_constraint("fk_agent_run_parent", type_="foreignkey")
        batch.drop_constraint("fk_agent_run_invocation", type_="foreignkey")
        batch.drop_column("intent")
        batch.drop_column("parent_run_id")
        batch.drop_column("invocation_queue_entry_id")
    op.drop_table("agent_invocation_queue")
    with op.batch_alter_table("handoff_records") as batch:
        batch.drop_index("ix_handoff_records_parent_handoff_id")
        batch.drop_constraint("fk_handoff_completed_message", type_="foreignkey")
        batch.drop_constraint("fk_handoff_parent", type_="foreignkey")
        batch.drop_column("depth")
        batch.drop_column("completed_message_id")
        batch.drop_column("parent_handoff_id")
        batch.drop_column("intent")
