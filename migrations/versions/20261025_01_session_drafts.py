"""Persist resumable workout snapshots separately from completed history.

Additive migration: existing sessions, sets, source links and timestamps are untouched.
Downgrade removes draft snapshots; completed workouts remain.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261025_01"
down_revision = "20261024_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "session_draft",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("completed_session_id", sa.BigInteger(), sa.ForeignKey("training_session.id")),
        sa.UniqueConstraint("user_id", "client_session_id"),
    )
    op.create_index(
        "ix_session_draft_active_user",
        "session_draft",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("completed_session_id IS NULL"),
    )


def downgrade():
    op.drop_table("session_draft")
