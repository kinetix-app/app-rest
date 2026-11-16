"""Remove superseded shared foods without breaking saved references.

Revision ID: 20261116_03
Revises: 20261116_02
"""

from alembic import op

revision = "20261116_03"
down_revision = "20261116_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy shared rows predate catalog_key. Preserve any referenced row as inactive so
    # existing recipes and diary entries retain their source and historical totals.
    op.execute(
        """
        UPDATE food
        SET is_active = FALSE
        WHERE user_id IS NULL
          AND catalog_key IS NULL
          AND (
              EXISTS (SELECT 1 FROM recipe_ingredient WHERE recipe_ingredient.food_id = food.id)
              OR EXISTS (SELECT 1 FROM meal_item WHERE meal_item.food_id = food.id)
          )
        """
    )
    op.execute(
        """
        DELETE FROM food
        WHERE user_id IS NULL
          AND catalog_key IS NULL
          AND NOT EXISTS (SELECT 1 FROM recipe_ingredient WHERE recipe_ingredient.food_id = food.id)
          AND NOT EXISTS (SELECT 1 FROM meal_item WHERE meal_item.food_id = food.id)
        """
    )


def downgrade() -> None:
    # Deleted legacy catalogue rows cannot be reconstructed safely.
    pass
