"""Add asset category and commissioning date indexes.

Revision ID: 20260919_0005
Revises: 20260919_0004
Create Date: 2026-09-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260919_0005"
down_revision: str | None = "20260919_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_assets_category", "assets", ["category"])
    op.create_index("ix_assets_commissioned_on", "assets", ["commissioned_on"])


def downgrade() -> None:
    op.drop_index("ix_assets_commissioned_on", table_name="assets")
    op.drop_index("ix_assets_category", table_name="assets")

