"""Support dated body measurements and explicit weight targets.

Revision ID: 20261121_01
Revises: 20261120_03
"""

import sqlalchemy as sa
from alembic import op

revision = "20261121_01"
down_revision = "20261120_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("body_measurement", sa.Column("height_cm", sa.Numeric(5, 2)))
    op.add_column("body_measurement", sa.Column("request_id", sa.Uuid()))
    for column in ("weight_kg", "muscle_mass_kg"):
        op.alter_column(
            "body_measurement", column, existing_type=sa.Numeric(5, 2), type_=sa.Numeric(10, 6)
        )
    op.create_unique_constraint(None, "body_measurement", ["user_id", "request_id"])
    op.create_index(
        "ix_body_measurement_user_id_date_id", "body_measurement", ["user_id", "date", "id"]
    )

    op.add_column(
        "physical_goal",
        sa.Column(
            "target_metric",
            sa.String(16),
            comment="Values: weight_kg (kg); NULL preserves legacy targets of unspecified metric.",
        ),
    )
    op.alter_column(
        "physical_goal", "target_value", existing_type=sa.Numeric(8, 2), type_=sa.Numeric(12, 6)
    )
    op.create_unique_constraint(None, "physical_goal", ["user_id", "goal_type", "target_metric"])


def downgrade() -> None:
    # Reject an unsafe downgrade rather than rounding observations or losing target provenance.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM body_measurement
                WHERE height_cm IS NOT NULL OR request_id IS NOT NULL
                   OR abs(weight_kg) > 999.99 OR weight_kg <> round(weight_kg, 2)
                   OR abs(muscle_mass_kg) > 999.99 OR muscle_mass_kg <> round(muscle_mass_kg, 2)
            ) OR EXISTS (SELECT 1 FROM physical_goal WHERE target_metric IS NOT NULL) THEN
                RAISE EXCEPTION 'Body measurements or explicit weight targets would lose data';
            END IF;
        END
        $$;
    """)
    op.drop_constraint(op.f("uq_physical_goal_user_id"), "physical_goal", type_="unique")
    op.alter_column(
        "physical_goal", "target_value", existing_type=sa.Numeric(12, 6), type_=sa.Numeric(8, 2)
    )
    op.drop_column("physical_goal", "target_metric")

    op.drop_index("ix_body_measurement_user_id_date_id", table_name="body_measurement")
    op.drop_constraint(op.f("uq_body_measurement_user_id"), "body_measurement", type_="unique")
    for column in ("weight_kg", "muscle_mass_kg"):
        op.alter_column(
            "body_measurement", column, existing_type=sa.Numeric(10, 6), type_=sa.Numeric(5, 2)
        )
    op.drop_column("body_measurement", "request_id")
    op.drop_column("body_measurement", "height_cm")
