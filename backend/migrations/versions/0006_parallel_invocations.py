"""add explicit parallel agent invocations

Revision ID: 0006_parallel_invocations
Revises: 0005_mention_execution
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_parallel_invocations"
down_revision: str | None = "0005_mention_execution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "parallel_invocation_requests" not in tables:
        op.create_table(
            "parallel_invocation_requests",
            sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
            sa.Column("conversation_id", sa.Uuid(native_uuid=False), nullable=False),
            sa.Column("turn_id", sa.Uuid(native_uuid=False), nullable=False),
            sa.Column("source_message_id", sa.BigInteger(), nullable=False),
            sa.Column("initiator_agent_id", sa.String(100), nullable=False),
            sa.Column("callback_agent_id", sa.String(100), nullable=False),
            sa.Column("targets", sa.JSON(), nullable=False),
            sa.Column("question", sa.String(4000), nullable=False),
            sa.Column("context", sa.String(4000), nullable=False, server_default=""),
            sa.Column("idempotency_key", sa.Uuid(native_uuid=False), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("aggregated_message_id", sa.BigInteger()),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["turn_id"], ["conversation_turns.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["source_message_id"], ["conversation_messages.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["aggregated_message_id"], ["conversation_messages.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "conversation_id",
                "idempotency_key",
                name="uq_parallel_request_idempotency",
            ),
            mysql_charset="utf8mb4",
            mysql_engine="InnoDB",
        )
        op.create_index(
            "ix_parallel_invocation_requests_conversation_id",
            "parallel_invocation_requests",
            ["conversation_id"],
        )
        op.create_index(
            "ix_parallel_invocation_requests_turn_id",
            "parallel_invocation_requests",
            ["turn_id"],
        )
        op.create_index(
            "ix_parallel_invocation_requests_status",
            "parallel_invocation_requests",
            ["status"],
        )
        op.create_index(
            "ix_parallel_invocation_requests_deadline_at",
            "parallel_invocation_requests",
            ["deadline_at"],
        )

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "parallel_invocation_responses" not in tables:
        op.create_table(
            "parallel_invocation_responses",
            sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
            sa.Column("request_id", sa.Uuid(native_uuid=False), nullable=False),
            sa.Column("target_agent_id", sa.String(100), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
            sa.Column("content", sa.JSON()),
            sa.Column("error_type", sa.String(100)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["request_id"], ["parallel_invocation_requests.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "request_id", "target_agent_id", name="uq_parallel_response_target"
            ),
            mysql_charset="utf8mb4",
            mysql_engine="InnoDB",
        )
        op.create_index(
            "ix_parallel_invocation_responses_request_id",
            "parallel_invocation_responses",
            ["request_id"],
        )

    queue_columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("agent_invocation_queue")
    }
    with op.batch_alter_table("agent_invocation_queue") as batch:
        if "parallel_request_id" not in queue_columns:
            batch.add_column(sa.Column("parallel_request_id", sa.Uuid(native_uuid=False)))
            batch.create_foreign_key(
                "fk_invocation_queue_parallel_request",
                "parallel_invocation_requests",
                ["parallel_request_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch.create_index(
                "ix_agent_invocation_queue_parallel_request_id", ["parallel_request_id"]
            )
        if "parallel_response_id" not in queue_columns:
            batch.add_column(sa.Column("parallel_response_id", sa.Uuid(native_uuid=False)))
            batch.create_foreign_key(
                "fk_invocation_queue_parallel_response",
                "parallel_invocation_responses",
                ["parallel_response_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch.create_unique_constraint(
                "uq_agent_invocation_queue_parallel_response_id", ["parallel_response_id"]
            )


def downgrade() -> None:
    with op.batch_alter_table("agent_invocation_queue") as batch:
        batch.drop_constraint("uq_agent_invocation_queue_parallel_response_id", type_="unique")
        batch.drop_constraint("fk_invocation_queue_parallel_response", type_="foreignkey")
        batch.drop_constraint("fk_invocation_queue_parallel_request", type_="foreignkey")
        batch.drop_index("ix_agent_invocation_queue_parallel_request_id")
        batch.drop_column("parallel_response_id")
        batch.drop_column("parallel_request_id")
    op.drop_table("parallel_invocation_responses")
    op.drop_table("parallel_invocation_requests")
