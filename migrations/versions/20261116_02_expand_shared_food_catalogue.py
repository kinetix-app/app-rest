"""Add Spanish staples and useful cooked/raw food variants.

Revision ID: 20261116_02
Revises: 20261116_01
"""

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert

revision = "20261116_02"
down_revision = "20261116_01"
branch_labels = None
depends_on = None

CATALOGUE_PATH = (
    Path(__file__).resolve().parents[2] / "app" / "features" / "nutrition" / "base_foods.json"
)


def upgrade() -> None:
    rows = [
        {"user_id": None, "is_active": True, **item}
        for item in json.loads(CATALOGUE_PATH.read_text())
    ]
    food = sa.table(
        "food",
        sa.column("user_id", sa.BigInteger()),
        sa.column("catalog_key", sa.String(100)),
        sa.column("name", sa.String(150)),
        sa.column("brand", sa.String(100)),
        sa.column("calories", sa.Numeric(8, 2)),
        sa.column("protein", sa.Numeric(8, 2)),
        sa.column("carbohydrates", sa.Numeric(8, 2)),
        sa.column("fats", sa.Numeric(8, 2)),
        sa.column("barcode", sa.String(50)),
        sa.column("is_active", sa.Boolean()),
    )
    op.get_bind().execute(
        insert(food).values(rows).on_conflict_do_nothing(index_elements=[food.c.catalog_key])
    )


def downgrade() -> None:
    # Catalogue foods may already be referenced by meal entries or recipes.
    # Keep them instead of risking destructive downgrade failures.
    pass
