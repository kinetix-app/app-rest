"""Rename profile measurement preference and preserve each existing choice.

Revision ID: 20261025_06
Revises: 20261025_05
"""

import sqlalchemy as sa
from alembic import op

revision = "20261025_06"
down_revision = "20261025_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "profiles",
        "weight_unit",
        new_column_name="measurement_system",
        existing_type=sa.String(length=2),
        type_=sa.String(length=8),
        existing_nullable=True,
        comment="Values: metric, imperial",
        existing_comment="Values: kg, lb",
    )
    op.execute(
        "UPDATE profiles SET measurement_system = CASE measurement_system "
        "WHEN 'kg' THEN 'metric' WHEN 'lb' THEN 'imperial' "
        "ELSE measurement_system END"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE profiles SET measurement_system = CASE measurement_system "
        "WHEN 'metric' THEN 'kg' WHEN 'imperial' THEN 'lb' "
        "ELSE measurement_system END"
    )
    op.alter_column(
        "profiles",
        "measurement_system",
        new_column_name="weight_unit",
        existing_type=sa.String(length=8),
        type_=sa.String(length=2),
        existing_nullable=True,
        comment="Values: kg, lb",
        existing_comment="Values: metric, imperial",
    )
