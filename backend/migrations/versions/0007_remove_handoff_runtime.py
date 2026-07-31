"""remove legacy handoff runtime

Revision ID: 0007_remove_handoff_runtime
Revises: 0006_parallel_invocations
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_remove_handoff_runtime"
down_revision: str | None = "0006_parallel_invocations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_foreign_keys_for_column(table: str, column: str) -> None:
    inspector = sa.inspect(op.get_bind())
    names = [
        constraint["name"]
        for constraint in inspector.get_foreign_keys(table)
        if column in constraint.get("constrained_columns", ()) and constraint.get("name")
    ]
    if not names:
        return
    with op.batch_alter_table(table) as batch:
        for name in names:
            batch.drop_constraint(name, type_="foreignkey")


def upgrade() -> None:
    for table, columns in (
        ("conversation_messages", ("handoff_id",)),
        ("agent_runs", ("handoff_id", "parent_run_id")),
        (
            "agent_invocation_queue",
            ("handoff_id", "parent_invocation_id", "depth"),
        ),
    ):
        existing = {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}
        for column in columns:
            if column in existing:
                _drop_foreign_keys_for_column(table, column)
        with op.batch_alter_table(table) as batch:
            for column in columns:
                if column not in existing:
                    continue
                index = f"ix_{table}_{column}"
                indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
                if index in indexes:
                    batch.drop_index(index)
                batch.drop_column(column)

    if "handoff_records" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("handoff_records")


def downgrade() -> None:
    raise NotImplementedError(
        "legacy handoff data and schema are intentionally not restorable"
    )
