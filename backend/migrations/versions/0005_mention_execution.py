"""link mention execution requests to controlled tasks

Revision ID: 0005_mention_execution
Revises: 0004_agent_invocation_queue
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_mention_execution"
down_revision: str | None = "0004_agent_invocation_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    task_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("tasks")}
    if "originating_invocation_id" in task_columns:
        return
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("originating_invocation_id", sa.Uuid(native_uuid=False)))
        batch.create_unique_constraint(
            "uq_tasks_originating_invocation_id", ["originating_invocation_id"]
        )
        batch.create_index("ix_tasks_originating_invocation_id", ["originating_invocation_id"])


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_index("ix_tasks_originating_invocation_id")
        batch.drop_constraint("uq_tasks_originating_invocation_id", type_="unique")
        batch.drop_column("originating_invocation_id")
