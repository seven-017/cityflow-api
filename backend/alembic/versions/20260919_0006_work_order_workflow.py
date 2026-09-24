"""Add platform work-order workflow fields and history tables.

Revision ID: 20260919_0006
Revises: 20260919_0005
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260919_0006"
down_revision: str | None = "20260919_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "work_orders",
        sa.Column("assigned_title", sa.String(length=150), nullable=True),
    )
    op.add_column(
        "work_orders",
        sa.Column("source_notes", sa.Text(), nullable=True),
    )
    op.add_column(
        "work_orders",
        sa.Column("priority", sa.String(length=2), nullable=True),
    )
    op.add_column(
        "work_orders",
        sa.Column("sla_policy", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "work_orders",
        sa.Column("sla_deadline", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "work_orders",
        sa.Column("sla_source", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "work_orders",
        sa.Column("created_by_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "work_orders",
        sa.Column("assigned_to_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_work_orders_created_by_id_users",
        "work_orders",
        "users",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_work_orders_assigned_to_id_users",
        "work_orders",
        "users",
        ["assigned_to_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_work_orders_priority", "work_orders", ["priority"])
    op.create_index("ix_work_orders_assigned_to_id", "work_orders", ["assigned_to_id"])
    op.create_index("ix_work_orders_sla_deadline", "work_orders", ["sla_deadline"])

    op.create_table(
        "work_order_status_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("work_order_id", sa.BigInteger(), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("operator_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["users.id"],
            name="fk_work_order_status_history_operator_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["work_order_id"],
            ["work_orders.id"],
            name="fk_work_order_status_history_work_order_id_work_orders",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_work_order_status_history"),
    )
    op.create_index(
        "ix_work_order_status_history_created_at",
        "work_order_status_history",
        ["created_at"],
    )
    op.create_index(
        "ix_work_order_status_history_work_order_id",
        "work_order_status_history",
        ["work_order_id"],
    )

    op.create_table(
        "work_order_processing_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("work_order_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_work_order_processing_records_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["work_order_id"],
            ["work_orders.id"],
            name="fk_work_order_processing_records_work_order_id_work_orders",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_work_order_processing_records"),
    )
    op.create_index(
        "ix_work_order_processing_records_created_at",
        "work_order_processing_records",
        ["created_at"],
    )
    op.create_index(
        "ix_work_order_processing_records_work_order_id",
        "work_order_processing_records",
        ["work_order_id"],
    )


def downgrade() -> None:
    op.drop_table("work_order_processing_records")
    op.drop_table("work_order_status_history")
    op.drop_index("ix_work_orders_sla_deadline", table_name="work_orders")
    op.drop_index("ix_work_orders_assigned_to_id", table_name="work_orders")
    op.drop_index("ix_work_orders_priority", table_name="work_orders")
    op.drop_constraint(
        "fk_work_orders_assigned_to_id_users",
        "work_orders",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_work_orders_created_by_id_users",
        "work_orders",
        type_="foreignkey",
    )
    op.drop_column("work_orders", "assigned_to_id")
    op.drop_column("work_orders", "created_by_id")
    op.drop_column("work_orders", "sla_source")
    op.drop_column("work_orders", "sla_deadline")
    op.drop_column("work_orders", "sla_policy")
    op.drop_column("work_orders", "priority")
    op.drop_column("work_orders", "source_notes")
    op.drop_column("work_orders", "assigned_title")

