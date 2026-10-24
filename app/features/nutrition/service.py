from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.nutrition.models import food, meal, meal_item, nutrition_day, nutrition_goal
from app.features.nutrition.schemas import FoodCreate, FoodPatch, MealItemCreate, NutritionGoalInput


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


async def search_foods(db: AsyncSession, user_id: int, name: str):
    result = await db.execute(
        select(food)
        .where(food.c.user_id == user_id, food.c.name.icontains(name.strip(), autoescape=True))
        .order_by(food.c.name, food.c.id)
        .limit(20)
    )
    return result.mappings().all()


async def create_meal_item(db: AsyncSession, user_id: int, data: MealItemCreate):
    source = (
        (await db.execute(select(food).where(food.c.id == data.food_id, food.c.user_id == user_id)))
        .mappings()
        .one_or_none()
    )
    if source is None:
        return None
    # The ownership lookup starts SQLAlchemy's implicit read transaction.
    # Close it before opening the atomic day/meal/item write transaction.
    await db.rollback()
    async with db.begin():
        day = (
            (
                await db.execute(
                    select(nutrition_day).where(
                        nutrition_day.c.user_id == user_id, nutrition_day.c.date == data.date
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if day is None:
            day = (
                (
                    await db.execute(
                        nutrition_day.insert()
                        .values(user_id=user_id, date=data.date)
                        .returning(nutrition_day)
                    )
                )
                .mappings()
                .one()
            )
        entry = (
            (
                await db.execute(
                    select(meal).where(
                        meal.c.nutrition_day_id == day["id"], meal.c.meal_type == data.meal_type
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if entry is None:
            entry = (
                (
                    await db.execute(
                        meal.insert()
                        .values(nutrition_day_id=day["id"], meal_type=data.meal_type)
                        .returning(meal)
                    )
                )
                .mappings()
                .one()
            )
        item = (
            (
                await db.execute(
                    meal_item.insert()
                    .values(
                        meal_id=entry["id"],
                        food_id=data.food_id,
                        quantity_grams=data.quantity_grams,
                    )
                    .returning(meal_item.c.id)
                )
            )
            .mappings()
            .one()
        )
    multiplier = data.quantity_grams / 100
    return {
        "id": item["id"],
        "meal_type": data.meal_type,
        "food_id": data.food_id,
        "name": source["name"],
        "quantity_grams": data.quantity_grams,
        "calories": source["calories"] * multiplier,
        "protein": source["protein"] * multiplier,
        "carbohydrates": source["carbohydrates"] * multiplier,
        "fats": source["fats"] * multiplier,
    }


async def get_nutrition_day(db: AsyncSession, user_id: int, day_date):
    rows = (
        (
            await db.execute(
                select(
                    meal.c.meal_type,
                    meal_item.c.id,
                    meal_item.c.food_id,
                    meal_item.c.quantity_grams,
                    food.c.name,
                    food.c.calories,
                    food.c.protein,
                    food.c.carbohydrates,
                    food.c.fats,
                )
                .select_from(
                    nutrition_day.join(meal)
                    .join(meal_item)
                    .join(food, meal_item.c.food_id == food.c.id)
                )
                .where(nutrition_day.c.user_id == user_id, nutrition_day.c.date == day_date)
            )
        )
        .mappings()
        .all()
    )
    totals = {"calories": 0, "protein": 0, "carbohydrates": 0, "fats": 0}
    items = []
    for row in rows:
        factor = row["quantity_grams"] / 100
        item = {
            "id": row["id"],
            "meal_type": row["meal_type"],
            "food_id": row["food_id"],
            "name": row["name"],
            "quantity_grams": row["quantity_grams"],
            **{key: row[key] * factor for key in totals},
        }
        items.append(item)
        for key in totals:
            totals[key] += item[key]
    return {"date": day_date, **totals, "items": items}


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
    stmt = select(nutrition_goal).where(nutrition_goal.c.user_id == user_id)

    result = await db.execute(stmt)
    return result.mappings().one_or_none()


async def create_nutrition_goal(db: AsyncSession, user_id: int, data: NutritionGoalInput):
    try:
        result = await db.execute(
            insert(nutrition_goal)
            .values(user_id=user_id, **data.model_dump())
            .returning(nutrition_goal)
        )
        await db.commit()
        return result.mappings().one()
    except Exception:
        await db.rollback()
        raise


async def update_nutrition_goal(db: AsyncSession, user_id: int, data: NutritionGoalInput):
    try:
        result = await db.execute(
            update(nutrition_goal)
            .where(nutrition_goal.c.user_id == user_id)
            .values(**data.model_dump())
            .returning(nutrition_goal)
        )
        await db.commit()
        return result.mappings().one_or_none()
    except Exception:
        await db.rollback()
        raise
