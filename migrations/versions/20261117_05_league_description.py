"""Add optional league descriptions for invitation previews."""

import sqlalchemy as sa
from alembic import op

revision = "20261117_05"
down_revision = "20261117_04"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("league", sa.Column("description", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("league", "description")
