"""Remove tables left behind by retired execution flows.

The runtime now stores executable plans in ``execution_plans`` and
``execution_steps``.  ``proposals`` belonged to the retired proposal flow.
``conversation_context_summaries`` was introduced by an abandoned context
compression experiment and has no runtime model or repository.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_cleanup_legacy_tables"
down_revision: str | None = "0011_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table in ("conversation_context_summaries", "proposals"):
        if table in tables:
            op.drop_table(table)


def downgrade() -> None:
    # The removed tables are intentionally not recreated.  They have no
    # corresponding runtime models and restoring them would reintroduce dead
    # schema.  A downgrade therefore stops at the cleaned schema boundary.
    pass
