"""Add mutual friendships and the FRIENDS post visibility.

Revision ID: 20261120_03
Revises: 20261120_02
"""

import sqlalchemy as sa
from alembic import op

revision = "20261120_03"
down_revision = "20261120_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "friendship",
        sa.Column("user_low_id", sa.BigInteger(), nullable=False),
        sa.Column("user_high_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "requester_id",
            sa.BigInteger(),
            nullable=False,
            comment="Account that sent the request; one of the pair",
        ),
        sa.Column(
            "status", sa.String(length=8), nullable=False, comment="Values: PENDING, ACCEPTED"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_low_id"], ["users.id"], name=op.f("fk_friendship_user_low_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["user_high_id"], ["users.id"], name=op.f("fk_friendship_user_high_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["requester_id"], ["users.id"], name=op.f("fk_friendship_requester_id_users")
        ),
        sa.PrimaryKeyConstraint("user_low_id", "user_high_id", name=op.f("pk_friendship")),
    )
    op.create_index(op.f("ix_friendship_user_high_id"), "friendship", ["user_high_id"])
    op.alter_column(
        "post",
        "visibility",
        existing_type=sa.String(length=7),
        existing_nullable=False,
        comment="Values: PUBLIC, PRIVATE, LEAGUE, FRIENDS",
        existing_comment="Values: PUBLIC, PRIVATE, LEAGUE",
    )


def downgrade() -> None:
    # Friends-only posts become private so they never widen their audience.
    op.execute("UPDATE post SET visibility = 'PRIVATE' WHERE visibility = 'FRIENDS'")
    op.alter_column(
        "post",
        "visibility",
        existing_type=sa.String(length=7),
        existing_nullable=False,
        comment="Values: PUBLIC, PRIVATE, LEAGUE",
        existing_comment="Values: PUBLIC, PRIVATE, LEAGUE, FRIENDS",
    )
    op.drop_index(op.f("ix_friendship_user_high_id"), table_name="friendship")
    op.drop_table("friendship")
