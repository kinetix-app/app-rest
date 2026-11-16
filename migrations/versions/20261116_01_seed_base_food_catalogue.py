"""Seed the shared starter food catalogue.

Revision ID: 20261116_01
Revises: 20261103_02
"""

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "20261116_01"
down_revision = "20261103_02"
branch_labels = None
depends_on = None

CATALOGUE_PATH = (
    Path(__file__).resolve().parents[2] / "app" / "features" / "nutrition" / "base_foods.json"
)


def base_foods() -> list[dict[str, str | None]]:
    return json.loads(CATALOGUE_PATH.read_text())


def upgrade() -> None:
    op.execute("ALTER TABLE food ADD COLUMN catalog_key VARCHAR(100) UNIQUE")
    rows = [{"user_id": None, "is_active": True, **item} for item in base_foods()]
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
    op.bulk_insert(food, rows)


def downgrade() -> None:
    op.execute("ALTER TABLE food DROP CONSTRAINT food_catalog_key_key")
    op.drop_column("food", "catalog_key")
