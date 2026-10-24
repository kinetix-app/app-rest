from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.nutrition.models import (
    food,
    meal,
    meal_item,
    nutrition_day,
    nutrition_goal,
    recipe,
    recipe_ingredient,
)
from app.features.nutrition.schemas import (
    FoodCreate,
    FoodPatch,
    MealItemCreate,
    NutritionGoalInput,
    RecipeCreate,
    RecipeMealItemCreate,
)


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
) -> str:
    source = (
        await db.execute(select(food.c.id).where(food.c.id == food_id, food.c.user_id == user_id))
    ).scalar_one_or_none()
    if source is None:
        return "not_found"
    is_used = (
        await db.execute(
            select(meal_item.c.id)
            .where(meal_item.c.food_id == food_id)
            .union(select(recipe_ingredient.c.id).where(recipe_ingredient.c.food_id == food_id))
            .limit(1)
        )
    ).scalar_one_or_none()
    if is_used is not None:
        return "in_use"
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

    return "deleted" if deleted_id is not None else "not_found"


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


async def search_foods(db: AsyncSession, user_id: int, name: str | None = None):
    stmt = select(food).where(food.c.user_id == user_id)
    if name and name.strip():
        result = await db.execute(
            stmt.where(food.c.name.icontains(name.strip(), autoescape=True))
            .order_by(food.c.name, food.c.id)
            .limit(20)
        )
    else:
        result = await db.execute(stmt.order_by(func.random()).limit(3))
    return result.mappings().all()


async def create_recipe(db: AsyncSession, user_id: int, data: RecipeCreate):
    food_ids = {ingredient.food_id for ingredient in data.ingredients}
    owned_food_ids = set(
        (
            await db.execute(
                select(food.c.id).where(food.c.user_id == user_id, food.c.id.in_(food_ids))
            )
        )
        .scalars()
        .all()
    )
    if owned_food_ids != food_ids:
        return None

    await db.rollback()
    async with db.begin():
        created = (
            (
                await db.execute(
                    insert(recipe)
                    .values(user_id=user_id, name=data.name, servings=data.servings)
                    .returning(recipe)
                )
            )
            .mappings()
            .one()
        )
        await db.execute(
            insert(recipe_ingredient),
            [
                {
                    "recipe_id": created["id"],
                    "food_id": ingredient.food_id,
                    "quantity_grams": ingredient.quantity_grams,
                }
                for ingredient in data.ingredients
            ],
        )
    return (await get_recipes(db, user_id, recipe_id=created["id"]))[0]


async def get_recipes(db: AsyncSession, user_id: int, recipe_id: int | None = None):
    conditions = [recipe.c.user_id == user_id]
    if recipe_id is not None:
        conditions.append(recipe.c.id == recipe_id)
    rows = (
        (
            await db.execute(
                select(
                    recipe.c.id,
                    recipe.c.user_id,
                    recipe.c.name,
                    recipe.c.servings,
                    recipe_ingredient.c.quantity_grams,
                    food.c.calories,
                    food.c.protein,
                    food.c.carbohydrates,
                    food.c.fats,
                )
                .select_from(recipe.join(recipe_ingredient).join(food))
                .where(*conditions)
                .order_by(recipe.c.name, recipe.c.id)
            )
        )
        .mappings()
        .all()
    )
    recipes = {}
    for row in rows:
        item = recipes.setdefault(
            row["id"],
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "name": row["name"],
                "servings": row["servings"],
                "calories": 0,
                "protein": 0,
                "carbohydrates": 0,
                "fats": 0,
            },
        )
        factor = row["quantity_grams"] / 100 / row["servings"]
        for macro in ("calories", "protein", "carbohydrates", "fats"):
            item[macro] += row[macro] * factor
    return list(recipes.values())


async def delete_recipe(db: AsyncSession, user_id: int, recipe_id: int) -> str:
    recipe_row = (
        await db.execute(
            select(recipe.c.id).where(recipe.c.id == recipe_id, recipe.c.user_id == user_id)
        )
    ).scalar_one_or_none()
    if recipe_row is None:
        return "not_found"
    is_logged = (
        await db.execute(select(meal_item.c.id).where(meal_item.c.recipe_id == recipe_id).limit(1))
    ).scalar_one_or_none()
    if is_logged is not None:
        return "in_use"
    try:
        await db.execute(
            delete(recipe_ingredient).where(recipe_ingredient.c.recipe_id == recipe_id)
        )
        await db.execute(
            delete(recipe).where(recipe.c.id == recipe_id, recipe.c.user_id == user_id)
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return "deleted"


async def create_recipe_meal_item(db: AsyncSession, user_id: int, data: RecipeMealItemCreate):
    recipes = await get_recipes(db, user_id, recipe_id=data.recipe_id)
    if not recipes:
        return None
    source = recipes[0]
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
        item_id = (
            await db.execute(
                meal_item.insert()
                .values(meal_id=entry["id"], recipe_id=data.recipe_id, servings=data.servings)
                .returning(meal_item.c.id)
            )
        ).scalar_one()
    return {
        "id": item_id,
        "meal_type": data.meal_type,
        "recipe_id": data.recipe_id,
        "name": source["name"],
        "servings": data.servings,
        **{
            macro: source[macro] * data.servings
            for macro in ("calories", "protein", "carbohydrates", "fats")
        },
    }


async def delete_meal_item(db: AsyncSession, user_id: int, meal_item_id: int) -> bool:
    owned_item = (
        select(meal_item.c.id)
        .select_from(meal_item.join(meal).join(nutrition_day))
        .where(meal_item.c.id == meal_item_id, nutrition_day.c.user_id == user_id)
    )
    deleted = (
        await db.execute(
            delete(meal_item)
            .where(
                meal_item.c.id.in_(owned_item),
            )
            .returning(meal_item.c.id)
        )
    ).scalar_one_or_none()
    await db.commit()
    return deleted is not None


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
    recipe_rows = (
        (
            await db.execute(
                select(
                    meal.c.meal_type,
                    meal_item.c.id,
                    meal_item.c.recipe_id,
                    meal_item.c.servings.label("logged_servings"),
                    recipe.c.name,
                    recipe.c.servings.label("recipe_servings"),
                    recipe_ingredient.c.quantity_grams,
                    food.c.calories,
                    food.c.protein,
                    food.c.carbohydrates,
                    food.c.fats,
                )
                .select_from(
                    nutrition_day.join(meal)
                    .join(meal_item)
                    .join(recipe, meal_item.c.recipe_id == recipe.c.id)
                    .join(recipe_ingredient, recipe_ingredient.c.recipe_id == recipe.c.id)
                    .join(food, recipe_ingredient.c.food_id == food.c.id)
                )
                .where(nutrition_day.c.user_id == user_id, nutrition_day.c.date == day_date)
            )
        )
        .mappings()
        .all()
    )
    recipe_items = {}
    for row in recipe_rows:
        item = recipe_items.setdefault(
            row["id"],
            {
                "id": row["id"],
                "meal_type": row["meal_type"],
                "recipe_id": row["recipe_id"],
                "name": row["name"],
                "servings": row["logged_servings"],
                **{key: 0 for key in totals},
            },
        )
        factor = row["quantity_grams"] / 100 / row["recipe_servings"] * row["logged_servings"]
        for key in totals:
            item[key] += row[key] * factor
    for item in recipe_items.values():
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
