"""Leagues, membership, calendar rounds and per-user round scores."""

import sqlalchemy as sa

from app.db.base import Base

USER_ID_REFERENCE = "users.id"
LEAGUE_ID_REFERENCE = "league.id"

league = sa.Table(
    "league",
    Base.metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column("name", sa.Text(), nullable=False),
    sa.Column("description", sa.Text(), nullable=True),
    sa.Column("timezone", sa.String(100), nullable=True),
    sa.Column("picture_blob_name", sa.Text(), nullable=True),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column("created_by", sa.BigInteger(), sa.ForeignKey(USER_ID_REFERENCE), nullable=False),
)

league_member = sa.Table(
    "league_member",
    Base.metadata,
    sa.Column("user_id", sa.BigInteger(), sa.ForeignKey(USER_ID_REFERENCE), primary_key=True),
    sa.Column("league_id", sa.BigInteger(), sa.ForeignKey(LEAGUE_ID_REFERENCE), primary_key=True),
    sa.Column("joined_date", sa.Date(), nullable=False, server_default=sa.text("CURRENT_DATE")),
    sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("role", sa.String(16), nullable=True, comment="Values: admin, member"),
)

league_round = sa.Table(
    "league_round",
    Base.metadata,
    sa.Column("id", sa.BigInteger, primary_key=True),
    sa.Column("league_id", sa.BigInteger, sa.ForeignKey(LEAGUE_ID_REFERENCE), nullable=False),
    sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("league_id", "start_at"),
    sa.UniqueConstraint("league_id", "id", name="uq_league_round_league_id_id"),
)

league_score = sa.Table(
    "league_score",
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
        ["league_id", "round_id"], ["league_round.league_id", "league_round.id"]
    ),
    sa.ForeignKeyConstraint(
        ["session_id", "user_id"], ["training_session.id", "training_session.user_id"]
    ),
)

league_invitation = sa.Table(
    "league_invitation",
    Base.metadata,
    sa.Column("token_hash", sa.String(64), primary_key=True),
    sa.Column("league_id", sa.BigInteger(), sa.ForeignKey(LEAGUE_ID_REFERENCE), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
)
