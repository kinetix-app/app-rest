"""Completed workout precision, idempotency and source provenance.

Legacy naive training event values are explicitly interpreted as UTC, independent
of the connection/server timezone. Historical values and nullable legacy keys stay.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261024_01"
down_revision = "20261021_03"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("routine_exercise_set", "exercise_set"):
        op.alter_column(table, "weight_kg", type_=sa.Numeric(12, 6), existing_type=sa.Numeric(8, 2))
    for column in ("started_at", "ended_at"):
        op.alter_column(
            "training_session",
            column,
            type_=sa.DateTime(timezone=True),
            existing_type=sa.DateTime(),
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )
    op.add_column("training_session", sa.Column("client_session_id", postgresql.UUID(as_uuid=True)))
    op.add_column("training_session", sa.Column("payload_fingerprint", sa.String(64)))
    op.create_unique_constraint(None, "training_session", ["user_id", "client_session_id"])
    op.create_table(
        "routine_slot_provenance",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("routine_id", sa.BigInteger(), nullable=False),
        sa.Column("routine_exercise_id", sa.BigInteger(), nullable=False),
        sa.Column("exercise_id", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("routine_exercise_id", "exercise_id"),
    )


def downgrade():
    op.drop_table("routine_slot_provenance")
    op.drop_constraint(op.f("uq_training_session_user_id"), "training_session", type_="unique")
    op.drop_column("training_session", "payload_fingerprint")
    op.drop_column("training_session", "client_session_id")
    for column in ("started_at", "ended_at"):
        op.alter_column(
            "training_session",
            column,
            type_=sa.DateTime(),
            existing_type=sa.DateTime(timezone=True),
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )
    for table in ("routine_exercise_set", "exercise_set"):
        op.alter_column(table, "weight_kg", type_=sa.Numeric(8, 2), existing_type=sa.Numeric(12, 6))
