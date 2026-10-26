"""Store an internal private profile picture reference without changing legacy URLs.

Revision ID: 20261025_05
Revises: 20261025_04
"""

import sqlalchemy as sa
from alembic import op

revision = "20261025_05"
down_revision = "20261025_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("picture_blob_name", sa.Text(), nullable=True))


def downgrade() -> None:
    # Relative delivery URLs have no meaning once their hidden reference is removed.
    op.execute("UPDATE profiles SET picture_url = NULL WHERE picture_blob_name IS NOT NULL")
    op.drop_column("profiles", "picture_blob_name")
