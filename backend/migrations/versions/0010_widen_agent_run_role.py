"""Widen agent role values used by the parent/child collaboration runtime."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_widen_agent_run_role"
down_revision: str | None = "0009_long_term_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.alter_column(
            "role",
            existing_type=sa.String(length=32),
            type_=sa.String(length=128),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.alter_column(
            "role",
            existing_type=sa.String(length=128),
            type_=sa.String(length=32),
            existing_nullable=True,
        )
