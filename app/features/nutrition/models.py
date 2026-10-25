"""Persistence metadata for the initial product schema; APIs are feature work."""

import sqlalchemy as sa

from app.db.base import Base

food = sa.Table(
    "food",
    Base.metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
    sa.Column("name", sa.String(150), nullable=False),
    sa.Column("brand", sa.String(100), nullable=True),
    sa.Column("calories", sa.Numeric(8, 2), nullable=False),
    sa.Column("protein", sa.Numeric(8, 2), nullable=False),
    sa.Column("carbohydrates", sa.Numeric(8, 2), nullable=False),
    sa.Column("fats", sa.Numeric(8, 2), nullable=False),
    sa.Column("barcode", sa.String(50), nullable=True),
)

recipe = sa.Table(
    "recipe",
    Base.metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
    sa.Column("name", sa.String(150), nullable=False),
    sa.Column("description", sa.Text(), nullable=True),
    sa.Column("instructions", sa.Text(), nullable=True),
    sa.Column("servings", sa.Integer(), nullable=False, server_default=sa.text("1")),
)

recipe_ingredient = sa.Table(
    "recipe_ingredient",
    Base.metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column("recipe_id", sa.BigInteger(), sa.ForeignKey("recipe.id"), nullable=False),
    sa.Column("food_id", sa.BigInteger(), sa.ForeignKey("food.id"), nullable=False),
    sa.Column("quantity_grams", sa.Numeric(8, 2), nullable=False),
)

nutrition_day = sa.Table(
    "nutrition_day",
    Base.metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
    sa.Column("date", sa.Date(), nullable=False),
)

meal = sa.Table(
    "meal",
    Base.metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column(
        "nutrition_day_id", sa.BigInteger(), sa.ForeignKey("nutrition_day.id"), nullable=False
    ),
    sa.Column(
        "meal_type",
        sa.String(30),
        nullable=False,
        comment="Proposed values: breakfast, lunch, dinner, snack; final meal categories pending.",
    ),
)

meal_item = sa.Table(
    "meal_item",
    Base.metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column("meal_id", sa.BigInteger(), sa.ForeignKey("meal.id"), nullable=False),
    sa.Column("food_id", sa.BigInteger(), sa.ForeignKey("food.id"), nullable=True),
    sa.Column("recipe_id", sa.BigInteger(), sa.ForeignKey("recipe.id"), nullable=True),
    sa.Column("quantity_grams", sa.Numeric(8, 2), nullable=True),
    sa.Column("servings", sa.Numeric(8, 2), nullable=True),
)

nutrition_goal = sa.Table(
    "nutrition_goal",
    Base.metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True),
    sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False, unique=True),
    sa.Column(
        "objective",
        sa.String(50),
        nullable=True,
        comment="Selected objective at explicit target save; null for legacy/unset context.",
    ),
    sa.Column("calories", sa.Numeric(8, 2), nullable=False),
    sa.Column("protein", sa.Numeric(8, 2), nullable=False),
    sa.Column("carbohydrates", sa.Numeric(8, 2), nullable=False),
    sa.Column("fats", sa.Numeric(8, 2), nullable=False),
)
