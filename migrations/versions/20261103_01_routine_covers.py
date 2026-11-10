"""Add private routine cover references without changing existing templates.

Revision ID: 20261103_01
Revises: 20261102_01
"""

import sqlalchemy as sa
from alembic import op

revision = "20261103_01"
down_revision = "20261102_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("routine", sa.Column("picture_blob_name", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("routine", "picture_blob_name")
