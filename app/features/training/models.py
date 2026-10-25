"""Training persistence metadata shared by the routine API and exercise seed command."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db.base import Base

exercise = sa.Table(
    "exercise",
    Base.metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
    sa.Column(
        "activity_type",
        sa.String(30),
        nullable=False,
        comment="Values: gym, running, cycling, walking. Sprint 1 uses gym.",
    ),
    sa.Column("name", sa.Text(), nullable=False),
    sa.Column("overview", sa.Text(), nullable=True),
    sa.Column("body_parts", postgresql.ARRAY(sa.Text()), nullable=True),
    sa.Column("equipments", postgresql.ARRAY(sa.Text()), nullable=True),
    sa.Column(
        "exercise_types",
        postgresql.ARRAY(sa.String(50)),
        nullable=True,
        comment=(
            "Provider/manual classification, distinct from activity_type. "
            "Proposed values: strength, cardio, stretching, mobility; "
            "catalogue vocabulary pending."
        ),
    ),
    sa.Column("target_muscles", postgresql.ARRAY(sa.Text()), nullable=True),
    sa.Column("secondary_muscles", postgresql.ARRAY(sa.Text()), nullable=True),
    sa.Column("instructions", postgresql.ARRAY(sa.Text()), nullable=True),
    sa.Column("exercise_tips", postgresql.ARRAY(sa.Text()), nullable=True),
    sa.Column("variations", postgresql.ARRAY(sa.Text()), nullable=True),
    sa.Column("keywords", postgresql.ARRAY(sa.Text()), nullable=True),
    sa.Column(
        "difficulty",
        sa.String(20),
        nullable=True,
        comment=(
            "Proposed values: beginner, intermediate, advanced; catalogue vocabulary pending."
        ),
    ),
    sa.Column("related_exercise_ids", postgresql.ARRAY(sa.Text()), nullable=True),
    sa.Column("video_url", sa.Text(), nullable=True),
    sa.Column("image_url", sa.Text(), nullable=True),
    sa.Column("gif_urls", postgresql.JSONB(), nullable=True),
    sa.Column(
        "source",
        sa.String(30),
        nullable=False,
        server_default=sa.text("'manual'"),
        comment=(
            "Values: manual, ascend_edb_v1, ascend_edb_v2; extend when another source is added."
        ),
    ),
    sa.Column("external_id", sa.Text(), nullable=True),
    sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("image_urls", postgresql.JSONB(), nullable=True),
)

sa.Index(
    "ix_exercise_catalogue_source_external_id",
    exercise.c.source,
    exercise.c.external_id,
    unique=True,
    postgresql_where=sa.text("user_id IS NULL AND external_id IS NOT NULL AND source <> 'manual'"),
)

routine = sa.Table(
    "routine",
    Base.metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
    sa.Column("name", sa.String(150), nullable=False),
    sa.Column("description", sa.Text(), nullable=True),
    sa.Column(
        "created_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")
    ),
)

routine_exercise = sa.Table(
    "routine_exercise",
    Base.metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column("routine_id", sa.BigInteger(), sa.ForeignKey("routine.id"), nullable=False),
    sa.Column("exercise_id", sa.BigInteger(), sa.ForeignKey("exercise.id"), nullable=False),
    sa.Column("exercise_order", sa.Integer(), nullable=False),
    sa.Column("notes", sa.Text(), nullable=True),
)

routine_exercise_set = sa.Table(
    "routine_exercise_set",
    Base.metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column(
        "routine_exercise_id", sa.BigInteger(), sa.ForeignKey("routine_exercise.id"), nullable=False
    ),
    sa.Column("set_number", sa.Integer(), nullable=False),
    sa.Column("reps", sa.Integer(), nullable=True),
    sa.Column("weight_kg", sa.Numeric(12, 6), nullable=True),
    sa.Column("duration_seconds", sa.Integer(), nullable=True),
    sa.Column("distance_km", sa.Numeric(8, 2), nullable=True),
)

training_session = sa.Table(
    "training_session",
    Base.metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
    sa.Column("routine_id", sa.BigInteger(), sa.ForeignKey("routine.id"), nullable=True),
    sa.Column(
        "activity_type",
        sa.String(30),
        nullable=False,
        comment="Values: gym, running, cycling, walking. Sprint 1 uses gym.",
    ),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("notes", sa.Text(), nullable=True),
    sa.Column("client_session_id", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("payload_fingerprint", sa.String(64), nullable=True),
    sa.UniqueConstraint("user_id", "client_session_id"),
)

session_exercise = sa.Table(
    "session_exercise",
    Base.metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column("session_id", sa.BigInteger(), sa.ForeignKey("training_session.id"), nullable=False),
    sa.Column("exercise_id", sa.BigInteger(), sa.ForeignKey("exercise.id"), nullable=False),
    sa.Column("exercise_order", sa.Integer(), nullable=False),
    sa.Column("notes", sa.Text(), nullable=True),
)

exercise_set = sa.Table(
    "exercise_set",
    Base.metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column(
        "session_exercise_id", sa.BigInteger(), sa.ForeignKey("session_exercise.id"), nullable=False
    ),
    sa.Column("set_number", sa.Integer(), nullable=False),
    sa.Column("reps", sa.Integer(), nullable=True),
    sa.Column("weight_kg", sa.Numeric(12, 6), nullable=True),
    sa.Column("duration_seconds", sa.Integer(), nullable=True),
    sa.Column("distance_km", sa.Numeric(8, 2), nullable=True),
    sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
)

# Snapshots keep unconfirmed form values separate from completed workout history.
session_draft = sa.Table(
    "session_draft",
    Base.metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
    sa.Column("client_session_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("snapshot", postgresql.JSONB(), nullable=False),
    sa.Column("completed_session_id", sa.BigInteger(), sa.ForeignKey("training_session.id")),
    sa.Column(
        "finish_update_routine", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")
    ),
    sa.UniqueConstraint("user_id", "client_session_id"),
)
sa.Index(
    "ix_session_draft_active_user",
    session_draft.c.user_id,
    unique=True,
    postgresql_where=sa.text("completed_session_id IS NULL"),
)
