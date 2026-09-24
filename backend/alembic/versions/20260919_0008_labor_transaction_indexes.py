"""Add Labor and Transaction query indexes.

Revision ID: 20260919_0008
Revises: 20260919_0007
Create Date: 2026-09-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260919_0008"
down_revision: str | None = "20260919_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_work_order_labor_source_record_id",
        "work_order_labor",
        ["source_record_id"],
    )
    op.create_index(
        "ix_work_order_labor_search",
        "work_order_labor",
        ["action", "description"],
        mysql_prefix="FULLTEXT",
    )
    op.create_index(
        "ix_transactions_source_record_id",
        "transactions",
        ["source_record_id"],
    )
    op.create_index(
        "ix_transactions_request_number",
        "transactions",
        ["request_number"],
    )
    op.create_index(
        "ix_transactions_search",
        "transactions",
        ["description"],
        mysql_prefix="FULLTEXT",
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_search", table_name="transactions")
    op.drop_index("ix_transactions_request_number", table_name="transactions")
    op.drop_index("ix_transactions_source_record_id", table_name="transactions")
    op.drop_index("ix_work_order_labor_search", table_name="work_order_labor")
    op.drop_index(
        "ix_work_order_labor_source_record_id",
        table_name="work_order_labor",
    )

