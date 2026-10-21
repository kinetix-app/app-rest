
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete


from app.features.nutrition.models import food
from app.features.nutrition.schemas import FoodCreate


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