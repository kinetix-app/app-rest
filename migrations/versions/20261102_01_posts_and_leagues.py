"""Add Sprint 2 posts and leagues persistence.

Revision ID: 20261102_01
Revises: 20261025_06
"""

import sqlalchemy as sa
from alembic import op

revision = "20261102_01"
down_revision = "20261025_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Additive change: existing tables and rows are untouched.
    op.create_table(
        "post",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "visibility",
            sa.String(length=7),
            nullable=False,
            comment="Values: PUBLIC, PRIVATE, LEAGUE",
        ),
        sa.Column(
            "type", sa.String(length=14), nullable=False, comment="Values: SESSION, LEAGUE_PENALTY"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_post_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_post")),
    )
    op.create_table(
        "file",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("post_id", sa.BigInteger(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=5), nullable=False, comment="Values: IMAGE, VIDEO"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False, comment="Size in bytes"),
        sa.ForeignKeyConstraint(["post_id"], ["post.id"], name=op.f("fk_file_post_id_post")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_file")),
    )
    op.create_table(
        "post_like",
        sa.Column("post_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["post_id"], ["post.id"], name=op.f("fk_post_like_post_id_post")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_post_like_user_id_users")),
        sa.PrimaryKeyConstraint("post_id", "user_id", name=op.f("pk_post_like")),
    )
    op.create_table(
        "post_comment",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("post_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["post_id"], ["post.id"], name=op.f("fk_post_comment_post_id_post")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_post_comment_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_post_comment")),
    )
    op.create_table(
        "league",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_league_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_league")),
    )
    op.create_table(
        "league_member",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("league_id", sa.BigInteger(), nullable=False),
        sa.Column("joined_date", sa.Date(), server_default=sa.text("CURRENT_DATE"), nullable=False),
        sa.ForeignKeyConstraint(
            ["league_id"], ["league.id"], name=op.f("fk_league_member_league_id_league")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_league_member_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", "league_id", name=op.f("pk_league_member")),
    )
    op.create_table(
        "league_round",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("league_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["league_id"], ["league.id"], name=op.f("fk_league_round_league_id_league")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_league_round")),
    )
    op.create_table(
        "league_score",
        sa.Column("league_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("round_id", sa.BigInteger(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["league_id"], ["league.id"], name=op.f("fk_league_score_league_id_league")
        ),
        sa.ForeignKeyConstraint(
            ["round_id"], ["league_round.id"], name=op.f("fk_league_score_round_id_league_round")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_league_score_user_id_users")
        ),
        sa.PrimaryKeyConstraint("league_id", "user_id", "round_id", name=op.f("pk_league_score")),
    )


def downgrade() -> None:
    op.drop_table("league_score")
    op.drop_table("league_round")
    op.drop_table("league_member")
    op.drop_table("league")
    op.drop_table("post_comment")
    op.drop_table("post_like")
    op.drop_table("file")
    op.drop_table("post")
