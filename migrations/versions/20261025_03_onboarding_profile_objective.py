"""Add nullable profile setup and an independent selected objective.

Existing profiles remain incomplete until users explicitly provide each field.
No physical/nutrition targets or historical records are inferred or changed.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261025_03"
down_revision = "fe73e224195b"
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("height_cm", sa.Numeric(5, 2), nullable=True),
        sa.Column("weight_kg", sa.Numeric(10, 6), nullable=True),
        sa.Column("weight_unit", sa.String(2), nullable=True, comment="Values: kg, lb"),
        sa.Column("picture_url", sa.Text(), nullable=True),
    ):
        op.add_column("profiles", column)
    op.create_table(
        "account_objective",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "objective",
            sa.String(30),
            nullable=False,
            comment="Values: build_muscle, lose_fat, gain_weight, maintain_weight",
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade():
    op.drop_table("account_objective")
    for name in ("picture_url", "weight_unit", "weight_kg", "height_cm", "age"):
        op.drop_column("profiles", name)
