"""Persist project roots and bind conversations/tasks to source workspaces."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_projects"
down_revision: str | None = "0010_widen_agent_run_role"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "projects" not in tables:
        op.create_table(
            "projects",
            sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("root_path", sa.String(length=768), nullable=False),
            sa.Column("access_mode", sa.String(length=16), nullable=False, server_default="edit"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("root_path"),
            mysql_charset="utf8mb4",
            mysql_engine="InnoDB",
        )

    conversation_columns = {column["name"] for column in inspector.get_columns("conversations")}
    if "project_id" not in conversation_columns:
        op.add_column(
            "conversations",
            sa.Column("project_id", sa.Uuid(native_uuid=False), nullable=True),
        )
        op.create_index("ix_conversations_project_id", "conversations", ["project_id"])
        op.create_foreign_key(
            "fk_conversations_project_id_projects",
            "conversations",
            "projects",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )

    task_columns = {column["name"] for column in inspector.get_columns("tasks")}
    if "project_id" not in task_columns:
        op.add_column("tasks", sa.Column("project_id", sa.Uuid(native_uuid=False), nullable=True))
        op.create_index("ix_tasks_project_id", "tasks", ["project_id"])
        op.create_foreign_key(
            "fk_tasks_project_id_projects",
            "tasks",
            "projects",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    op.drop_constraint("fk_tasks_project_id_projects", "tasks", type_="foreignkey")
    op.drop_index("ix_tasks_project_id", table_name="tasks")
    op.drop_column("tasks", "project_id")
    op.drop_constraint("fk_conversations_project_id_projects", "conversations", type_="foreignkey")
    op.drop_index("ix_conversations_project_id", table_name="conversations")
    op.drop_column("conversations", "project_id")
    op.drop_table("projects")
