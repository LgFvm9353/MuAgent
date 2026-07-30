"""generalize tool governance records for conversations

Revision ID: 0003_tool_governance
Revises: 0002_conversations
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_tool_governance"
down_revision: str | None = "0002_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("conversation_turns") as batch:
        batch.add_column(
            sa.Column(
                "collaboration_mode",
                sa.String(32),
                nullable=False,
                server_default="parallel",
            )
        )
        batch.add_column(
            sa.Column(
                "collaboration_phase",
                sa.String(32),
                nullable=False,
                server_default="routing",
            )
        )
        batch.add_column(sa.Column("synthesize", sa.Boolean(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("lead_agent_id", sa.String(100), nullable=True))
        batch.add_column(sa.Column("lease_owner", sa.String(100), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("failure_reason", sa.String(100), nullable=True))
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("phase", sa.String(32), nullable=True))
        batch.add_column(sa.Column("role", sa.String(32), nullable=True))
        batch.add_column(sa.Column("skill_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("skill_version", sa.String(32), nullable=True))
        batch.add_column(sa.Column("skill_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("tool_rounds", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("tool_calls", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("resume_state", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("lease_owner", sa.String(100), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table("tool_calls") as batch:
        batch.alter_column("task_id", existing_type=sa.String(32), nullable=True)
        batch.alter_column("step_id", existing_type=sa.String(32), nullable=True)
        batch.alter_column("tool_name", existing_type=sa.String(100), type_=sa.String(255))
        batch.add_column(sa.Column("turn_id", sa.String(32), nullable=True))
        batch.add_column(sa.Column("agent_run_id", sa.String(32), nullable=True))
        batch.add_column(sa.Column("source", sa.String(32), nullable=False, server_default="local"))
        batch.add_column(sa.Column("server_id", sa.String(100), nullable=True))
        batch.add_column(sa.Column("risk", sa.String(32), nullable=False, server_default="low"))
        batch.add_column(sa.Column("arguments_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("schema_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("output_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("timeout_seconds", sa.Float(), nullable=True))
        batch.add_column(sa.Column("side_effect_state", sa.String(32), nullable=True))
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_tool_calls_turn",
            "conversation_turns",
            ["turn_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_tool_calls_agent_run",
            "agent_runs",
            ["agent_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_tool_calls_turn_id", ["turn_id"])
        batch.create_index("ix_tool_calls_agent_run_id", ["agent_run_id"])

    with op.batch_alter_table("confirmations") as batch:
        batch.alter_column("task_id", existing_type=sa.String(32), nullable=True)
        batch.alter_column("plan_id", existing_type=sa.String(32), nullable=True)
        batch.alter_column("approved", existing_type=sa.Boolean(), nullable=True)
        batch.alter_column("decided_by", existing_type=sa.String(100), nullable=True)
        batch.add_column(sa.Column("turn_id", sa.String(32), nullable=True))
        batch.add_column(sa.Column("tool_call_id", sa.String(32), nullable=True))
        batch.add_column(
            sa.Column("status", sa.String(32), nullable=False, server_default="decided")
        )
        batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_unique_constraint(
            "uq_confirmation_tool_call_hash", ["tool_call_id", "call_hash"]
        )

    for table in ("evidence_records", "audit_events"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("turn_id", sa.String(32), nullable=True))
            batch.add_column(sa.Column("agent_run_id", sa.String(32), nullable=True))
            batch.add_column(sa.Column("tool_call_id", sa.String(32), nullable=True))
    with op.batch_alter_table("evidence_records") as batch:
        batch.alter_column("task_id", existing_type=sa.String(32), nullable=True)
        batch.alter_column("step_id", existing_type=sa.String(32), nullable=True)


def downgrade() -> None:
    # Revision 0001 creates the current metadata for fresh installations; the base
    # downgrade removes these columns together with their tables.
    pass
