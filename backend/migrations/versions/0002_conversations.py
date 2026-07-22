"""Add persistent conversations around task runs.

Revision ID: 0002_conversations
Revises: 0001_initial
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_conversations"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "conversations" not in tables:
        op.create_table(
            "conversations",
            sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            mysql_charset="utf8mb4",
            mysql_engine="InnoDB",
        )
        op.create_index("ix_conversations_updated_at", "conversations", ["updated_at"])

    task_columns = {column["name"] for column in sa.inspect(bind).get_columns("tasks")}
    if "conversation_id" in task_columns:
        return

    op.add_column("tasks", sa.Column("conversation_id", sa.Uuid(native_uuid=False), nullable=True))
    op.execute(
        sa.text(
            """
            INSERT INTO conversations (id, title, created_at, updated_at)
            SELECT id,
                   LEFT(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(contract, '$.goal')), '历史任务'), 255),
                   created_at,
                   updated_at
            FROM tasks
            """
        )
    )
    op.execute(sa.text("UPDATE tasks SET conversation_id = id WHERE conversation_id IS NULL"))
    op.alter_column("tasks", "conversation_id", existing_type=sa.Uuid(native_uuid=False), nullable=False)
    op.create_index("ix_tasks_conversation_id", "tasks", ["conversation_id"])
    op.create_foreign_key(
        "fk_tasks_conversation_id_conversations",
        "tasks",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_tasks_conversation_id_conversations", "tasks", type_="foreignkey")
    op.drop_index("ix_tasks_conversation_id", table_name="tasks")
    op.drop_column("tasks", "conversation_id")
    op.drop_index("ix_conversations_updated_at", table_name="conversations")
    op.drop_table("conversations")
