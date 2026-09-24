"""Add source relationship lookup indexes.

Revision ID: 20260919_0003
Revises: 20260918_0002
Create Date: 2026-09-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260919_0003"
down_revision: str | None = "20260918_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_work_orders_asset_source_record_id",
        "work_orders",
        ["asset_source_record_id"],
    )
    op.create_index(
        "ix_work_order_labor_source_work_order_record_id",
        "work_order_labor",
        ["source_work_order_record_id"],
    )
    op.create_index(
        "ix_transactions_source_work_order_record_id",
        "transactions",
        ["source_work_order_record_id"],
    )
    op.create_index(
        "ix_transaction_details_transaction_source_record_id",
        "transaction_details",
        ["transaction_source_record_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_transaction_details_transaction_source_record_id",
        table_name="transaction_details",
    )
    op.drop_index(
        "ix_transactions_source_work_order_record_id",
        table_name="transactions",
    )
    op.drop_index(
        "ix_work_order_labor_source_work_order_record_id",
        table_name="work_order_labor",
    )
    op.drop_index(
        "ix_work_orders_asset_source_record_id",
        table_name="work_orders",
    )

