"""Store the user's usual activity category."""

import sqlalchemy as sa
from alembic import op

revision = "20261118_02"
down_revision = "20261118_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column(
            "activity_level",
            sa.String(16),
            nullable=True,
            comment="Values: sedentary, light, moderate, high, very_high",
        ),
    )


def downgrade() -> None:
    op.drop_column("profiles", "activity_level")
