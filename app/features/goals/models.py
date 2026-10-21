"""Persistence metadata for the initial product schema; APIs are feature work."""

import sqlalchemy as sa

from app.db.base import Base

physical_goal = sa.Table(
    "physical_goal",
    Base.metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
    sa.Column(
        "goal_type",
        sa.String(50),
        nullable=False,
        comment=(
            "Values: build_muscle, lose_fat, gain_weight, maintain_weight. "
            "Target metric/unit and interpretation remain pending DEC-01."
        ),
    ),
    sa.Column("target_value", sa.Numeric(8, 2), nullable=False),
    sa.Column("start_date", sa.Date(), nullable=False, server_default=sa.text("CURRENT_DATE")),
    sa.Column("target_date", sa.Date(), nullable=True),
    sa.Column("completed_at", sa.DateTime(), nullable=True),
)

body_measurement = sa.Table(
    "body_measurement",
    Base.metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
    sa.Column("date", sa.Date(), nullable=False, server_default=sa.text("CURRENT_DATE")),
    sa.Column("weight_kg", sa.Numeric(5, 2), nullable=True),
    sa.Column("body_fat_percentage", sa.Numeric(5, 2), nullable=True),
    sa.Column("muscle_mass_kg", sa.Numeric(5, 2), nullable=True),
    sa.Column("waist_cm", sa.Numeric(5, 2), nullable=True),
    sa.Column("chest_cm", sa.Numeric(5, 2), nullable=True),
    sa.Column("arm_cm", sa.Numeric(5, 2), nullable=True),
    sa.Column("thigh_cm", sa.Numeric(5, 2), nullable=True),
)
