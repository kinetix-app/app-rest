"""Snapshot workout titles and store optional post captions.

Revision ID: 20261122_04
Revises: 20261122_03
"""

import sqlalchemy as sa
from alembic import op

revision = "20261122_04"
down_revision = "20261122_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "training_session",
        sa.Column("title", sa.String(150), server_default="Training session", nullable=False),
    )
    op.execute("""
        UPDATE training_session AS workout
        SET title = btrim(source.name)
        FROM routine AS source
        WHERE workout.routine_id = source.id
          AND workout.user_id = source.user_id
          AND btrim(source.name) <> ''
    """)
    op.add_column("post", sa.Column("caption", sa.String(160), server_default="", nullable=False))


def downgrade() -> None:
    op.drop_column("post", "caption")
    op.drop_column("training_session", "title")
