"""Store the sex used for nutritional requirement estimates."""

import sqlalchemy as sa
from alembic import op

revision = "20261118_01"
down_revision = "20261109_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("sex", sa.String(6), nullable=True, comment="Values: male, female"),
    )


def downgrade() -> None:
    op.drop_column("profiles", "sex")
