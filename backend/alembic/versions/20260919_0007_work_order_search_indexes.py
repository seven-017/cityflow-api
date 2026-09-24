"""Add work-order search indexes.

Revision ID: 20260919_0007
Revises: 20260919_0006
Create Date: 2026-09-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260919_0007"
down_revision: str | None = "20260919_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_work_orders_source_record_id",
        "work_orders",
        ["source_record_id"],
    )
    op.create_index(
        "ix_work_orders_search",
        "work_orders",
        ["description", "assigned_title"],
        mysql_prefix="FULLTEXT",
    )


def downgrade() -> None:
    op.drop_index("ix_work_orders_search", table_name="work_orders")
    op.drop_index("ix_work_orders_source_record_id", table_name="work_orders")

