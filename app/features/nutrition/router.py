from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from app.core.auth.dependencies import CurrentUser
from app.db.session import DatabaseSession
from app.features.nutrition.schemas import (
    FoodCreate,
    FoodPatch,
    FoodResponse,
    MealItemCreate,
    MealItemResponse,
    NutritionDayResponse,
    NutritionGoalInput,
    NutritionGoalResponse,
    RecipeCreate,
    RecipeMealItemCreate,
    RecipeResponse,
)
from app.features.nutrition.service import (
    create_food,
    create_meal_item,
    create_nutrition_goal,
    create_recipe,
    create_recipe_meal_item,
    delete_food,
    delete_meal_item,
    delete_recipe,
    get_food,
    get_nutrition_day,
    get_nutrition_goal,
    get_recipes,
    search_foods,
    update_food,
    update_nutrition_goal,
)

router = APIRouter(prefix="/foods", tags=["nutrition"])
recipe_router = APIRouter(prefix="/recipes", tags=["nutrition"])

nutrition_goal_router = APIRouter(prefix="/nutrition-goals", tags=["nutrition"])


@nutrition_goal_router.get(
    "/me",
    response_model=NutritionGoalResponse,
)
async def read_nutrition_goal(
    user: CurrentUser,
    session: DatabaseSession,
) -> NutritionGoalResponse:
    goal = await get_nutrition_goal(session, user.id)

    if goal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nutrition goal not found",
        )

    return goal


@nutrition_goal_router.post(
    "", response_model=NutritionGoalResponse, status_code=status.HTTP_201_CREATED
)
async def post_nutrition_goal(
    data: NutritionGoalInput, user: CurrentUser, session: DatabaseSession
) -> NutritionGoalResponse:
    if await get_nutrition_goal(session, user.id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Nutrition goal already exists"
        )
    return await create_nutrition_goal(session, user.id, data)


@nutrition_goal_router.patch("/me", response_model=NutritionGoalResponse)
async def patch_nutrition_goal(
    data: NutritionGoalInput, user: CurrentUser, session: DatabaseSession
) -> NutritionGoalResponse:
    goal = await update_nutrition_goal(session, user.id, data)
    if goal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Nutrition goal not found"
        )
    return goal


@router.get("", response_model=list[FoodResponse])
async def get_foods(
    user: CurrentUser,
    session: DatabaseSession,
    name: str | None = Query(default=None, min_length=1, max_length=150),
) -> list[FoodResponse]:
    return await search_foods(session, user.id, name)


@recipe_router.post("", response_model=RecipeResponse, status_code=status.HTTP_201_CREATED)
async def post_recipe(
    data: RecipeCreate, user: CurrentUser, session: DatabaseSession
) -> RecipeResponse:
    created = await create_recipe(session, user.id, data)
    if created is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Food not found")
    return created


@recipe_router.get("", response_model=list[RecipeResponse])
async def read_recipes(user: CurrentUser, session: DatabaseSession) -> list[RecipeResponse]:
    return await get_recipes(session, user.id)


@recipe_router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_recipe(recipe_id: int, user: CurrentUser, session: DatabaseSession) -> None:
    result = await delete_recipe(session, user.id, recipe_id)
    if result == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    if result == "in_use":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A recipe already logged in the diary cannot be deleted",
        )


meal_router = APIRouter(prefix="/nutrition", tags=["nutrition"])


@meal_router.post(
    "/meal-items", response_model=MealItemResponse, status_code=status.HTTP_201_CREATED
)
async def post_meal_item(
    data: MealItemCreate, user: CurrentUser, session: DatabaseSession
) -> MealItemResponse:
    item = await create_meal_item(session, user.id, data)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Food not found")
    return item


@meal_router.delete("/meal-items/{meal_item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_meal_item(meal_item_id: int, user: CurrentUser, session: DatabaseSession) -> None:
    if not await delete_meal_item(session, user.id, meal_item_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meal item not found")


@meal_router.post(
    "/recipe-items", response_model=MealItemResponse, status_code=status.HTTP_201_CREATED
)
async def post_recipe_meal_item(
    data: RecipeMealItemCreate, user: CurrentUser, session: DatabaseSession
) -> MealItemResponse:
    item = await create_recipe_meal_item(session, user.id, data)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    return item


@meal_router.get("/days/{day_date}", response_model=NutritionDayResponse)
async def read_nutrition_day(
    day_date: date, user: CurrentUser, session: DatabaseSession
) -> NutritionDayResponse:
    return await get_nutrition_day(session, user.id, day_date)


# Endpoint to create a new food item for the authenticated user
@router.post("", response_model=FoodResponse, status_code=status.HTTP_201_CREATED)
async def post_food(
    data: FoodCreate,
    user: CurrentUser,
    session: DatabaseSession,
) -> FoodResponse:
    return await create_food(session, user.id, data)


# Endpoint to delete a food item by its ID for the authenticated user
@router.delete("/{food_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_food(
    food_id: int,
    user: CurrentUser,
    session: DatabaseSession,
) -> None:
    deleted = await delete_food(session, user.id, food_id)

    if deleted == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Food not found",
        )
    if deleted == "in_use":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A food used in a recipe or diary cannot be deleted",
        )


# Endpoint to retrieve a food item by its ID for the authenticated user
@router.get("/{food_id}", response_model=FoodResponse)
async def read_food(
    food_id: int,
    user: CurrentUser,
    session: DatabaseSession,
) -> FoodResponse:
    result = await get_food(session, user.id, food_id)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Food not found",
        )

    return result


# Endpoint to update a food item by its ID for the authenticated user
@router.patch("/{food_id}", response_model=FoodResponse)
async def patch_food(
    food_id: int,
    data: FoodPatch,
    user: CurrentUser,
    session: DatabaseSession,
) -> FoodResponse:
    try:
        updated = await update_food(session, user.id, food_id, data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Food not found",
        )

    return updated
