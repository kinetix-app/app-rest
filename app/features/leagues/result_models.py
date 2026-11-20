"""Stable versioned round results and independent membership acknowledgements."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base
from app.features.leagues.models import league_member

league_result = sa.Table(
    "league_result",
    Base.metadata,
    sa.Column("id", sa.BigInteger, primary_key=True),
    sa.Column("league_id", sa.BigInteger, nullable=False),
    sa.Column("round_id", sa.BigInteger, nullable=False, unique=True),
    sa.Column("snapshot", JSONB, nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.UniqueConstraint("league_id", "id"),
    sa.ForeignKeyConstraint(
        ["league_id", "round_id"], ["league_round.league_id", "league_round.id"]
    ),
)
league_member.append_column(sa.Column("last_seen_result_id", sa.BigInteger, nullable=True))
league_member.append_constraint(
    sa.ForeignKeyConstraint(
        ["league_id", "last_seen_result_id"], ["league_result.league_id", "league_result.id"]
    )
)
