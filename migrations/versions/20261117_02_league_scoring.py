"""Add isolated scoring snapshots and weekly/daily credit."""

import sqlalchemy as sa
from alembic import op

revision = "20261117_02"
down_revision = "20261117_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_training_session_id_user_id", "training_session", ["id", "user_id"]
    )
    op.create_table(
        "league_scoring_round",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("league_id", sa.BigInteger, sa.ForeignKey("league.id"), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("league_id", "start_at"),
        sa.UniqueConstraint("league_id", "id", name="uq_league_scoring_round_league_id_id"),
    )
    op.create_table(
        "league_session_calculation",
        sa.Column("session_id", sa.BigInteger, primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("score", sa.Numeric(40, 0)),
        sa.Column("volume_kg_reps", sa.Numeric(40, 6), nullable=False),
        sa.Column("duration_us", sa.BigInteger, nullable=False),
        sa.Column("body_weight_kg", sa.Numeric(10, 6)),
        sa.Column("formula_version", sa.String(100), nullable=False),
        sa.UniqueConstraint("session_id", "user_id"),
        sa.ForeignKeyConstraint(
            ["session_id", "user_id"], ["training_session.id", "training_session.user_id"]
        ),
    )
    op.create_table(
        "league_daily_score",
        sa.Column("league_id", sa.BigInteger, primary_key=True),
        sa.Column("user_id", sa.BigInteger, primary_key=True),
        sa.Column("local_day", sa.Date, primary_key=True),
        sa.Column("round_id", sa.BigInteger, nullable=False),
        sa.Column("session_id", sa.BigInteger, nullable=False),
        sa.Column("score", sa.Numeric(40, 0), nullable=False),
        sa.Column("volume_kg_reps", sa.Numeric(40, 6), nullable=False),
        sa.Column("duration_us", sa.BigInteger, nullable=False),
        sa.Column("body_weight_kg", sa.Numeric(10, 6), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("formula_version", sa.String(100), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id", "league_id"], ["league_member.user_id", "league_member.league_id"]
        ),
        sa.ForeignKeyConstraint(
            ["league_id", "round_id"], ["league_scoring_round.league_id", "league_scoring_round.id"]
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "user_id"],
            ["league_session_calculation.session_id", "league_session_calculation.user_id"],
        ),
    )


def downgrade() -> None:
    op.drop_table("league_daily_score")
    op.drop_table("league_session_calculation")
    op.drop_table("league_scoring_round")
    op.drop_constraint("uq_training_session_id_user_id", "training_session", type_="unique")
