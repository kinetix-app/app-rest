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
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column("start_date", sa.Date(), nullable=False),
    sa.Column("end_date", sa.Date(), nullable=False),
    sa.Column("league_id", sa.BigInteger(), sa.ForeignKey(LEAGUE_ID_REFERENCE), nullable=False),
)

league_score = sa.Table(
    "league_score",
    Base.metadata,
    sa.Column("league_id", sa.BigInteger(), sa.ForeignKey(LEAGUE_ID_REFERENCE), primary_key=True),
    sa.Column("user_id", sa.BigInteger(), sa.ForeignKey(USER_ID_REFERENCE), primary_key=True),
    sa.Column("round_id", sa.BigInteger(), sa.ForeignKey("league_round.id"), primary_key=True),
    sa.Column("score", sa.Integer(), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)

league_invitation = sa.Table(
    "league_invitation",
    Base.metadata,
    sa.Column("token_hash", sa.String(64), primary_key=True),
    sa.Column("league_id", sa.BigInteger(), sa.ForeignKey(LEAGUE_ID_REFERENCE), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
)
