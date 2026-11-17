"""Document the GENERAL post type for posts without a shared workout.

Revision ID: 20261110_02
Revises: 20261110_01
"""

import sqlalchemy as sa
from alembic import op

revision = "20261110_02"
down_revision = "20261110_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Comment-only change: VARCHAR categories have no CHECK constraint.
    op.alter_column(
        "post",
        "type",
        existing_type=sa.String(length=14),
        existing_nullable=False,
        comment="Values: SESSION, LEAGUE_PENALTY, GENERAL",
        existing_comment="Values: SESSION, LEAGUE_PENALTY",
    )


def downgrade() -> None:
    op.execute("UPDATE post SET type = 'SESSION' WHERE type = 'GENERAL'")
    op.alter_column(
        "post",
        "type",
        existing_type=sa.String(length=14),
        existing_nullable=False,
        comment="Values: SESSION, LEAGUE_PENALTY",
        existing_comment="Values: SESSION, LEAGUE_PENALTY, GENERAL",
    )
