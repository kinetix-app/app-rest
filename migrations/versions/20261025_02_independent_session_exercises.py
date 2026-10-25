"""Decouple performed exercises from template slots and freeze finish decisions.

All workout, exercise and set rows remain. Only obsolete slot associations and
retained slot ownership metadata are removed. Downgrade cannot reconstruct those
associations; it recreates empty metadata and nullable links.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261025_02"
down_revision = "20261025_01"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("session_exercise", "routine_exercise_id")
    op.drop_table("routine_slot_provenance")
    op.add_column(
        "session_draft",
        sa.Column(
            "finish_update_routine", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")
        ),
    )
    # JSON drafts from the previous client remain resumable without obsolete slot IDs.
    op.execute(
        sa.text("""
        UPDATE session_draft SET snapshot = jsonb_set(snapshot, '{exercises}',
            COALESCE((SELECT jsonb_agg(value - 'routine_exercise_id' ORDER BY ordinality)
                      FROM jsonb_array_elements(snapshot -> 'exercises') WITH ORDINALITY),
                     '[]'::jsonb))
    """)
    )


def downgrade():
    op.drop_column("session_draft", "finish_update_routine")
    op.add_column(
        "session_exercise",
        sa.Column(
            "routine_exercise_id",
            sa.BigInteger(),
            sa.ForeignKey("routine_exercise.id", ondelete="SET NULL"),
        ),
    )
    op.create_table(
        "routine_slot_provenance",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("routine_id", sa.BigInteger(), nullable=False),
        sa.Column("routine_exercise_id", sa.BigInteger(), nullable=False),
        sa.Column("exercise_id", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("routine_exercise_id", "exercise_id"),
    )
