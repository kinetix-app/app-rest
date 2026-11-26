"""Store the application language on each profile.

Revision ID: 20261126_01
Revises: 20261122_04
"""

import sqlalchemy as sa
from alembic import op

revision = "20261126_01"
down_revision = "20261122_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column(
            "language", sa.String(2), nullable=False, server_default="en", comment="Values: en, es"
        ),
    )


def downgrade() -> None:
    op.drop_column("profiles", "language")
