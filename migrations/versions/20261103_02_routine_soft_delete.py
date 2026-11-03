"""Retain completed training provenance when an owned routine is deleted.

Revision ID: 20261103_02
Revises: 20261103_01
"""

import sqlalchemy as sa
from alembic import op

revision = "20261103_02"
down_revision = "20261103_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("routine", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # Restores deleted routines to visibility; completed references are never removed.
    op.drop_column("routine", "deleted_at")
