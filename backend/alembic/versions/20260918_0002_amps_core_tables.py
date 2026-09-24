"""Create core AMPS data tables.

Revision ID: 20260918_0002
Revises: 20260918_0001
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260918_0002"
down_revision: str | None = "20260918_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_record_id", sa.String(length=100), nullable=False),
        sa.Column("data_source", sa.String(length=32), nullable=False),
        sa.Column("asset_type", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("asset_class", sa.String(length=100), nullable=True),
        sa.Column("category", sa.String(length=150), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("parent_source_record_id", sa.String(length=100), nullable=True),
        sa.Column("manufacturer", sa.String(length=255), nullable=True),
        sa.Column("mrc_code", sa.String(length=100), nullable=True),
        sa.Column("serial_number", sa.String(length=255), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("record_code", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=100), nullable=True),
        sa.Column("commissioned_on", sa.Date(), nullable=True),
        sa.Column("withdrawn_on", sa.Date(), nullable=True),
        sa.Column("record_value", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("source_update_count", sa.Integer(), nullable=True),
        sa.Column("source_created_at", sa.DateTime(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
        sa.Column("gis_object_id", sa.String(length=100), nullable=True),
        sa.Column("gis_layer", sa.String(length=100), nullable=True),
        sa.Column("x_location", sa.Numeric(precision=18, scale=7), nullable=True),
        sa.Column("y_location", sa.Numeric(precision=18, scale=7), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_assets"),
        sa.UniqueConstraint(
            "data_source",
            "source_record_id",
            name="uq_assets_data_source_source_record_id",
        ),
    )
    op.create_index("ix_assets_asset_type", "assets", ["asset_type"])
    op.create_index("ix_assets_location", "assets", ["location"])
    op.create_index("ix_assets_status", "assets", ["status"])

    op.create_table(
        "work_orders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_record_id", sa.String(length=100), nullable=False),
        sa.Column("data_source", sa.String(length=32), nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=True),
        sa.Column("asset_source_record_id", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("work_type", sa.String(length=150), nullable=True),
        sa.Column("work_class", sa.String(length=150), nullable=True),
        sa.Column("request_date", sa.Date(), nullable=True),
        sa.Column("created_source_at", sa.DateTime(), nullable=True),
        sa.Column("completion_date", sa.Date(), nullable=True),
        sa.Column("scheduled_end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("status_origin", sa.String(length=32), nullable=False),
        sa.Column("source_status", sa.String(length=100), nullable=True),
        sa.Column("source_priority", sa.String(length=50), nullable=True),
        sa.Column("route", sa.String(length=100), nullable=True),
        sa.Column("target", sa.String(length=150), nullable=True),
        sa.Column("duration", sa.String(length=100), nullable=True),
        sa.Column("job_type", sa.String(length=150), nullable=True),
        sa.Column("parent_source_record_id", sa.String(length=100), nullable=True),
        sa.Column("is_ppm", sa.Boolean(), nullable=True),
        sa.Column("is_safety", sa.Boolean(), nullable=True),
        sa.Column("is_reopened", sa.Boolean(), nullable=True),
        sa.Column("has_warranty", sa.Boolean(), nullable=True),
        sa.Column("source_update_count", sa.Integer(), nullable=True),
        sa.Column("source_updated_raw", sa.String(length=255), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            name="fk_work_orders_asset_id_assets",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_work_orders"),
        sa.UniqueConstraint(
            "data_source",
            "source_record_id",
            name="uq_work_orders_data_source_source_record_id",
        ),
    )
    op.create_index("ix_work_orders_asset_id", "work_orders", ["asset_id"])
    op.create_index("ix_work_orders_completion_date", "work_orders", ["completion_date"])
    op.create_index("ix_work_orders_request_date", "work_orders", ["request_date"])
    op.create_index("ix_work_orders_status", "work_orders", ["status"])
    op.create_index("ix_work_orders_work_type", "work_orders", ["work_type"])

    op.create_table(
        "work_order_labor",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_record_id", sa.String(length=100), nullable=False),
        sa.Column("data_source", sa.String(length=32), nullable=False),
        sa.Column("work_order_id", sa.BigInteger(), nullable=True),
        sa.Column("source_work_order_record_id", sa.String(length=100), nullable=True),
        sa.Column("action", sa.String(length=255), nullable=True),
        sa.Column("work_date", sa.Date(), nullable=True),
        sa.Column("trade", sa.String(length=150), nullable=True),
        sa.Column("operation_type", sa.String(length=100), nullable=True),
        sa.Column("on_text", sa.String(length=100), nullable=True),
        sa.Column("off_text", sa.String(length=100), nullable=True),
        sa.Column("hours", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("rate", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("cost", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("entered_at", sa.DateTime(), nullable=True),
        sa.Column("correction_flag", sa.Boolean(), nullable=True),
        sa.Column("job_category", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("misc", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["work_order_id"],
            ["work_orders.id"],
            name="fk_work_order_labor_work_order_id_work_orders",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_work_order_labor"),
        sa.UniqueConstraint(
            "data_source",
            "source_record_id",
            name="uq_work_order_labor_data_source_source_record_id",
        ),
    )
    op.create_index("ix_work_order_labor_trade", "work_order_labor", ["trade"])
    op.create_index("ix_work_order_labor_work_date", "work_order_labor", ["work_date"])
    op.create_index(
        "ix_work_order_labor_work_order_id",
        "work_order_labor",
        ["work_order_id"],
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_record_id", sa.String(length=100), nullable=False),
        sa.Column("data_source", sa.String(length=32), nullable=False),
        sa.Column("work_order_id", sa.BigInteger(), nullable=True),
        sa.Column("source_work_order_record_id", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("transaction_type", sa.String(length=100), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=True),
        sa.Column("request_number", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=100), nullable=True),
        sa.Column("from_entity", sa.String(length=100), nullable=True),
        sa.Column("from_code", sa.String(length=150), nullable=True),
        sa.Column("to_entity", sa.String(length=100), nullable=True),
        sa.Column("to_code", sa.String(length=150), nullable=True),
        sa.Column("source_update_count", sa.Integer(), nullable=True),
        sa.Column("source_created_at", sa.DateTime(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["work_order_id"],
            ["work_orders.id"],
            name="fk_transactions_work_order_id_work_orders",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transactions"),
        sa.UniqueConstraint(
            "data_source",
            "source_record_id",
            name="uq_transactions_data_source_source_record_id",
        ),
    )
    op.create_index("ix_transactions_status", "transactions", ["status"])
    op.create_index(
        "ix_transactions_to_entity_code",
        "transactions",
        ["to_entity", "to_code"],
    )
    op.create_index(
        "ix_transactions_transaction_date",
        "transactions",
        ["transaction_date"],
    )
    op.create_index("ix_transactions_work_order_id", "transactions", ["work_order_id"])

    op.create_table(
        "transaction_details",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_record_id", sa.String(length=150), nullable=False),
        sa.Column("data_source", sa.String(length=32), nullable=False),
        sa.Column("transaction_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "transaction_source_record_id",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column("line_number", sa.String(length=100), nullable=True),
        sa.Column("detail_type", sa.String(length=100), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=True),
        sa.Column("event_source_record_id", sa.String(length=100), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=True),
        sa.Column("part_code", sa.String(length=150), nullable=True),
        sa.Column("part_description", sa.Text(), nullable=True),
        sa.Column("part_class", sa.String(length=100), nullable=True),
        sa.Column("part_uom", sa.String(length=50), nullable=True),
        sa.Column("requested_line", sa.String(length=100), nullable=True),
        sa.Column("bin_location", sa.String(length=100), nullable=True),
        sa.Column("store_code", sa.String(length=100), nullable=True),
        sa.Column("price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("average_price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("request_number", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("attachment", sa.String(length=255), nullable=True),
        sa.Column("source_created_at", sa.DateTime(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
        sa.Column("source_last_status_update", sa.String(length=255), nullable=True),
        sa.Column("source_sql_identity", sa.String(length=100), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name="fk_transaction_details_transaction_id_transactions",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transaction_details"),
        sa.UniqueConstraint(
            "data_source",
            "source_record_id",
            name="uq_transaction_details_data_source_source_record_id",
        ),
    )
    op.create_index(
        "ix_transaction_details_part_code",
        "transaction_details",
        ["part_code"],
    )
    op.create_index(
        "ix_transaction_details_transaction_id",
        "transaction_details",
        ["transaction_id"],
    )


def downgrade() -> None:
    op.drop_table("transaction_details")
    op.drop_table("transactions")
    op.drop_table("work_order_labor")
    op.drop_table("work_orders")
    op.drop_table("assets")

