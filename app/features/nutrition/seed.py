"""Synchronize the shared nutrition catalogue after database migrations."""

import asyncio
import json
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.session import create_database_engine
from app.features.nutrition.models import food, meal_item, recipe_ingredient

CATALOGUE_PATH = Path(__file__).with_name("base_foods.json")


def load_catalogue() -> list[dict[str, str | None]]:
    return json.loads(CATALOGUE_PATH.read_text())


def is_referenced(food_id):
    return sa.exists(sa.select(1).where(recipe_ingredient.c.food_id == food_id)) | sa.exists(
        sa.select(1).where(meal_item.c.food_id == food_id)
    )


def differs_from_catalogue(source, values: dict[str, str | None]) -> bool:
    fields = ("name", "brand", "calories", "protein", "carbohydrates", "fats", "barcode")
    return any(str(source[field]) != str(values[field]) for field in fields)


async def sync_base_foods(sessions: async_sessionmaker[AsyncSession]) -> None:
    catalogue = load_catalogue()
    keys = [item["catalog_key"] for item in catalogue]
    rows = [{"user_id": None, "is_active": True, **item} for item in catalogue]
    reference_exists = is_referenced(food.c.id)
    statement = insert(food).values(rows)
    async with sessions() as session:
        async with session.begin():
            existing = (
                await session.execute(
                    sa.select(food, reference_exists.label("is_referenced")).where(
                        food.c.user_id.is_(None), food.c.catalog_key.in_(keys)
                    )
                )
            ).mappings()
            catalogue_by_key = {item["catalog_key"]: item for item in catalogue}
            for source in existing:
                values = catalogue_by_key[source["catalog_key"]]
                if source["is_referenced"] and differs_from_catalogue(source, values):
                    await session.execute(
                        sa.update(food)
                        .where(food.c.id == source["id"])
                        .values(catalog_key=None, is_active=False)
                    )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[food.c.catalog_key],
                    set_={
                        column: statement.excluded[column]
                        for column in (
                            "name",
                            "brand",
                            "calories",
                            "protein",
                            "carbohydrates",
                            "fats",
                            "barcode",
                            "is_active",
                        )
                    },
                )
            )
            obsolete = food.c.user_id.is_(None) & (
                food.c.catalog_key.is_(None) | food.c.catalog_key.not_in(keys)
            )
            await session.execute(
                sa.update(food).where(obsolete, reference_exists).values(is_active=False)
            )
            await session.execute(sa.delete(food).where(obsolete, ~reference_exists))


async def run() -> None:
    engine = create_database_engine(Settings())
    try:
        await sync_base_foods(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()


def main() -> int:
    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
