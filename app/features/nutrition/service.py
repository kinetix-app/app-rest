
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

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
