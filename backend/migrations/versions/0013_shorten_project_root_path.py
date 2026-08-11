"""Keep the unique project-path key within InnoDB's byte limit."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_shorten_project_root_path"
down_revision: str | None = "0012_cleanup_legacy_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "projects" not in tables:
        return

    root_path = next(
        column for column in inspector.get_columns("projects") if column["name"] == "root_path"
    )
    current_length = getattr(root_path["type"], "length", None)
    if current_length is None or current_length <= 768:
        return

    too_long = bind.execute(
        sa.text("SELECT COUNT(*) FROM projects WHERE CHAR_LENGTH(root_path) > :limit"),
        {"limit": 768},
    ).scalar_one()
    if too_long:
        raise RuntimeError(
            "cannot shorten projects.root_path: existing paths exceed 768 characters"
        )

    op.alter_column(
        "projects",
        "root_path",
        existing_type=sa.String(length=current_length),
        type_=sa.String(length=768),
        existing_nullable=False,
    )


def downgrade() -> None:
    # The wider indexed column is not portable across MySQL configurations and
    # is intentionally not restored.
    pass
