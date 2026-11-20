"""Link posts to the shared completed workout and index feed child lookups.

Revision ID: 20261120_01
Revises: 20261117_06
"""

import sqlalchemy as sa
from alembic import op

revision = "20261120_01"
down_revision = "20261117_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Additive change: existing posts keep a NULL workout reference.
    op.add_column(
        "post",
        sa.Column(
            "training_session_id",
            sa.BigInteger(),
            nullable=True,
            comment="Shared completed workout; set for SESSION posts, at most one post per workout",
        ),
    )
    op.create_foreign_key(
        op.f("fk_post_training_session_id_training_session"),
        "post",
        "training_session",
        ["training_session_id"],
        ["id"],
    )
    op.create_unique_constraint(
        op.f("uq_post_training_session_id"), "post", ["training_session_id"]
    )
    op.create_index(op.f("ix_file_post_id"), "file", ["post_id"])
    op.create_index(op.f("ix_post_comment_post_id"), "post_comment", ["post_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_post_comment_post_id"), table_name="post_comment")
    op.drop_index(op.f("ix_file_post_id"), table_name="file")
    op.drop_constraint(op.f("uq_post_training_session_id"), "post", type_="unique")
    op.drop_constraint(
        op.f("fk_post_training_session_id_training_session"), "post", type_="foreignkey"
    )
    op.drop_column("post", "training_session_id")
