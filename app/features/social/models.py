"""One row per pair of accounts, stored with the lower ID first."""

from enum import StrEnum

import sqlalchemy as sa

from app.db.base import Base


class FriendshipStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"


friendship = sa.Table(
    "friendship",
    Base.metadata,
    sa.Column("user_low_id", sa.BigInteger(), sa.ForeignKey("users.id"), primary_key=True),
    sa.Column("user_high_id", sa.BigInteger(), sa.ForeignKey("users.id"), primary_key=True),
    sa.Column(
        "requester_id",
        sa.BigInteger(),
        sa.ForeignKey("users.id"),
        nullable=False,
        comment="Account that sent the request; one of the pair",
    ),
    sa.Column(
        "status",
        sa.Enum(
            FriendshipStatus, native_enum=False, create_constraint=False, validate_strings=True
        ),
        nullable=False,
        comment="Values: PENDING, ACCEPTED",
    ),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
)
sa.Index("ix_friendship_user_high_id", friendship.c.user_high_id)
