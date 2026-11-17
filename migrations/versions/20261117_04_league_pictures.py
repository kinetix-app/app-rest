"""Add optional private league profile pictures without altering existing data."""

import sqlalchemy as sa
from alembic import op

revision = "20261117_04"
down_revision = "20261117_03"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("league", sa.Column("picture_blob_name", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("league", "picture_blob_name")
