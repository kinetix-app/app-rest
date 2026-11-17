"""Versioned completed-workout calculations, rounds and daily winners."""

import sqlalchemy as sa

from app.db.base import Base
from app.features.training.models import training_session

# Enables a composite foreign key to enforce that each snapshot belongs to its source owner.
training_session.append_constraint(
    sa.UniqueConstraint("id", "user_id", name="uq_training_session_id_user_id")
)

league_scoring_round = sa.Table(
    "league_scoring_round",
    Base.metadata,
    sa.Column("id", sa.BigInteger, primary_key=True),
    sa.Column("league_id", sa.BigInteger, sa.ForeignKey("league.id"), nullable=False),
    sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("league_id", "start_at"),
    sa.UniqueConstraint("league_id", "id", name="uq_league_scoring_round_league_id_id"),
)

league_session_calculation = sa.Table(
    "league_session_calculation",
    Base.metadata,
    sa.Column("session_id", sa.BigInteger, primary_key=True),
    sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id"), nullable=False),
    sa.Column("score", sa.Numeric(40, 0), nullable=True),
    sa.Column("volume_kg_reps", sa.Numeric(40, 6), nullable=False),
    sa.Column("duration_us", sa.BigInteger, nullable=False),
    sa.Column("body_weight_kg", sa.Numeric(10, 6), nullable=True),
    sa.Column("formula_version", sa.String(100), nullable=False),
    sa.UniqueConstraint("session_id", "user_id"),
    sa.ForeignKeyConstraint(
        ["session_id", "user_id"], ["training_session.id", "training_session.user_id"]
    ),
)

league_daily_score = sa.Table(
    "league_daily_score",
    Base.metadata,
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
