from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.nutrition.models import food, nutrition_goal
from app.features.nutrition.schemas import FoodCreate, FoodPatch


# Service functions for managing food items in the database
async def create_food(
    db: AsyncSession,
    user_id: int,
    data: FoodCreate,
):
    stmt = (
        insert(food)
        .values(
            user_id=user_id,
            **data.model_dump(),
        )
        .returning(food)
    )

    try:
        result = await db.execute(stmt)
        created_food = result.mappings().one()
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return created_food


# Service function to delete a food item by its ID for a specific user
async def delete_food(
    db: AsyncSession,
    user_id: int,
    food_id: int,
) -> bool:
    stmt = (
        delete(food)
        .where(
            food.c.id == food_id,
            food.c.user_id == user_id,
        )
        .returning(food.c.id)
    )

    try:
        result = await db.execute(stmt)
        deleted_id = result.scalar_one_or_none()
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return deleted_id is not None


# Service function to retrieve a food item by its ID for a specific user
async def get_food(
    db: AsyncSession,
    user_id: int,
    food_id: int,
):
    stmt = select(food).where(
        food.c.id == food_id,
        food.c.user_id == user_id,
    )

    result = await db.execute(stmt)
    return result.mappings().one_or_none()


# Service function to update a food item by its ID for a specific user
async def update_food(
    db: AsyncSession,
    user_id: int,
    food_id: int,
    data: FoodPatch,
):
    changes = data.model_dump(exclude_unset=True)

    # No permitir valores nulos en campos obligatorios
    required = {"name", "calories", "protein", "carbohydrates", "fats"}
    if any(changes.get(field, 0) is None for field in required):
        raise ValueError("Required fields cannot be null")

    if not changes:
        return await get_food(db, user_id, food_id)

    stmt = (
        update(food)
        .where(
            food.c.id == food_id,
            food.c.user_id == user_id,
        )
        .values(**changes)
        .returning(food)
    )

    try:
        result = await db.execute(stmt)
        updated = result.mappings().one_or_none()
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return updated


async def get_nutrition_goal(
    db: AsyncSession,
    user_id: int,
):
    stmt = (
        select(nutrition_goal)
        .where(nutrition_goal.c.user_id == user_id)
    )

    result = await db.execute(stmt)
    return result.mappings().one_or_none()