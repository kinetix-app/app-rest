"""Guarantee one nutrition day and meal type per user and date.

Revision ID: 20261122_02
Revises: 20261122_01
"""

from alembic import op

revision = "20261122_02"
down_revision = "20261122_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preserve every logged item while moving it to the oldest equivalent parent row.
    op.execute("""
        WITH duplicates AS (
            SELECT id, min(id) OVER (PARTITION BY user_id, date) AS canonical_id
            FROM nutrition_day
        )
        UPDATE meal
        SET nutrition_day_id = duplicates.canonical_id
        FROM duplicates
        WHERE meal.nutrition_day_id = duplicates.id
          AND duplicates.id <> duplicates.canonical_id
    """)
    op.execute("""
        WITH duplicates AS (
            SELECT id, min(id) OVER (PARTITION BY user_id, date) AS canonical_id
            FROM nutrition_day
        )
        DELETE FROM nutrition_day
        USING duplicates
        WHERE nutrition_day.id = duplicates.id
          AND duplicates.id <> duplicates.canonical_id
    """)
    op.execute("""
        WITH duplicates AS (
            SELECT id, min(id) OVER (PARTITION BY nutrition_day_id, meal_type) AS canonical_id
            FROM meal
        )
        UPDATE meal_item
        SET meal_id = duplicates.canonical_id
        FROM duplicates
        WHERE meal_item.meal_id = duplicates.id
          AND duplicates.id <> duplicates.canonical_id
    """)
    op.execute("""
        WITH duplicates AS (
            SELECT id, min(id) OVER (PARTITION BY nutrition_day_id, meal_type) AS canonical_id
            FROM meal
        )
        DELETE FROM meal
        USING duplicates
        WHERE meal.id = duplicates.id
          AND duplicates.id <> duplicates.canonical_id
    """)
    op.create_unique_constraint(
        "uq_nutrition_day_user_id_date", "nutrition_day", ["user_id", "date"]
    )
    op.create_unique_constraint(
        "uq_meal_nutrition_day_id_meal_type", "meal", ["nutrition_day_id", "meal_type"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_meal_nutrition_day_id_meal_type", "meal", type_="unique")
    op.drop_constraint("uq_nutrition_day_user_id_date", "nutrition_day", type_="unique")
