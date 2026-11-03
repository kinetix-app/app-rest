"""Add active lifecycle state to reusable nutrition sources.

Revision ID: 20261103_01
Revises: 20261025_06
"""

import sqlalchemy as sa
from alembic import op

revision = "20261103_01"
down_revision = "20261025_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "food",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "recipe",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("recipe", "is_active")
    op.drop_column("food", "is_active")
