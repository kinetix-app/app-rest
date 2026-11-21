"""Persist stable round outcomes and membership-scoped acknowledgement."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261117_03"
down_revision = "20261117_02"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "league_result",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("league_id", sa.BigInteger, nullable=False),
        sa.Column("round_id", sa.BigInteger, nullable=False, unique=True),
        sa.Column("snapshot", JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("league_id", "id"),
        sa.ForeignKeyConstraint(
            ["league_id", "round_id"], ["league_scoring_round.league_id", "league_scoring_round.id"]
        ),
    )
    op.add_column("league_member", sa.Column("last_seen_result_id", sa.BigInteger, nullable=True))
    op.create_foreign_key(
        "fk_league_member_seen_result",
        "league_member",
        "league_result",
        ["league_id", "last_seen_result_id"],
        ["league_id", "id"],
    )


def downgrade():
    op.drop_constraint("fk_league_member_seen_result", "league_member", type_="foreignkey")
    op.drop_column("league_member", "last_seen_result_id")
    op.drop_table("league_result")
