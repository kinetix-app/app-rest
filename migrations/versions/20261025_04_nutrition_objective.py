"""Preserve the objective context of explicitly saved nutrition targets.

Revision ID: 20261025_04
Revises: 20261025_03
"""

import sqlalchemy as sa
from alembic import op

revision = "20261025_04"
down_revision = "20261025_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Do not infer an objective for existing user-selected targets.
    op.add_column(
        "nutrition_goal",
        sa.Column(
            "objective",
            sa.String(50),
            nullable=True,
            comment="Selected objective at explicit target save; null for legacy/unset context.",
        ),
    )


def downgrade() -> None:
    op.drop_column("nutrition_goal", "objective")
