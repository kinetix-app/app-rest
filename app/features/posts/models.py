"""Posts, attached bucket files, likes and comments."""

from enum import StrEnum

import sqlalchemy as sa

from app.db.base import Base

USER_ID_REFERENCE = "users.id"
POST_ID_REFERENCE = "post.id"


class PostVisibility(StrEnum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"
    LEAGUE = "LEAGUE"


class PostType(StrEnum):
    SESSION = "SESSION"
    LEAGUE_PENALTY = "LEAGUE_PENALTY"


class FileType(StrEnum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"


post = sa.Table(
    "post",
    Base.metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column("text", sa.Text(), nullable=False),
    sa.Column("user_id", sa.BigInteger(), sa.ForeignKey(USER_ID_REFERENCE), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "visibility",
        sa.Enum(PostVisibility, native_enum=False, create_constraint=False, validate_strings=True),
        nullable=False,
        comment="Values: PUBLIC, PRIVATE, LEAGUE",
    ),
    sa.Column(
        "type",
        sa.Enum(PostType, native_enum=False, create_constraint=False, validate_strings=True),
        nullable=False,
        comment="Values: SESSION, LEAGUE_PENALTY",
    ),
)

file = sa.Table(
    "file",
    Base.metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column("post_id", sa.BigInteger(), sa.ForeignKey(POST_ID_REFERENCE), nullable=False),
    sa.Column("order", sa.Integer(), nullable=False),
    sa.Column(
        "type",
        sa.Enum(FileType, native_enum=False, create_constraint=False, validate_strings=True),
        nullable=False,
        comment="Values: IMAGE, VIDEO",
    ),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column("url", sa.Text(), nullable=False),
    sa.Column("file_name", sa.Text(), nullable=False),
    sa.Column("file_size", sa.BigInteger(), nullable=False, comment="Size in bytes"),
)

post_like = sa.Table(
    "post_like",
    Base.metadata,
    sa.Column("post_id", sa.BigInteger(), sa.ForeignKey(POST_ID_REFERENCE), primary_key=True),
    sa.Column("user_id", sa.BigInteger(), sa.ForeignKey(USER_ID_REFERENCE), primary_key=True),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)

post_comment = sa.Table(
    "post_comment",
    Base.metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column("post_id", sa.BigInteger(), sa.ForeignKey(POST_ID_REFERENCE), nullable=False),
    sa.Column("user_id", sa.BigInteger(), sa.ForeignKey(USER_ID_REFERENCE), nullable=False),
    sa.Column("comment", sa.Text(), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)
