from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.core.auth.dependencies import CurrentUser
from app.db.session import DatabaseSession
from app.features.nutrition.errors import (
    FoodInUseError,
    FoodNotFoundError,
    MealItemNotFoundError,
    NutritionGoalNotFoundError,
    RecipeInUseError,
    RecipeNotFoundError,
)
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
FOOD_NOT_FOUND = "Food not found"


@nutrition_goal_router.get(
    "/me",
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


@nutrition_goal_router.post("", status_code=status.HTTP_201_CREATED)
async def post_nutrition_goal(
    data: NutritionGoalInput, user: CurrentUser, session: DatabaseSession
) -> NutritionGoalResponse:
    if await get_nutrition_goal(session, user.id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Nutrition goal already exists"
        )
    return await create_nutrition_goal(session, user.id, data)


@nutrition_goal_router.patch("/me")
async def patch_nutrition_goal(
    data: NutritionGoalInput, user: CurrentUser, session: DatabaseSession
) -> NutritionGoalResponse:
    try:
        return await update_nutrition_goal(session, user.id, data)
    except NutritionGoalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Nutrition goal not found"
        ) from exc


@router.get("")
async def get_foods(
    user: CurrentUser,
    session: DatabaseSession,
    name: Annotated[str | None, Query(min_length=1, max_length=150)] = None,
) -> list[FoodResponse]:
    return await search_foods(session, user.id, name)


@recipe_router.post("", status_code=status.HTTP_201_CREATED)
async def post_recipe(
    data: RecipeCreate, user: CurrentUser, session: DatabaseSession
) -> RecipeResponse:
    try:
        return await create_recipe(session, user.id, data)
    except FoodNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=FOOD_NOT_FOUND) from exc


@recipe_router.get("")
async def read_recipes(user: CurrentUser, session: DatabaseSession) -> list[RecipeResponse]:
    return await get_recipes(session, user.id)


@recipe_router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_recipe(recipe_id: int, user: CurrentUser, session: DatabaseSession) -> None:
    try:
        await delete_recipe(session, user.id, recipe_id)
    except RecipeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found"
        ) from exc
    except RecipeInUseError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A recipe already logged in the diary cannot be deleted",
        ) from exc


meal_router = APIRouter(prefix="/nutrition", tags=["nutrition"])


@meal_router.post("/meal-items", status_code=status.HTTP_201_CREATED)
async def post_meal_item(
    data: MealItemCreate, user: CurrentUser, session: DatabaseSession
) -> MealItemResponse:
    try:
        return await create_meal_item(session, user.id, data)
    except FoodNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=FOOD_NOT_FOUND) from exc


@meal_router.delete("/meal-items/{meal_item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_meal_item(meal_item_id: int, user: CurrentUser, session: DatabaseSession) -> None:
    try:
        await delete_meal_item(session, user.id, meal_item_id)
    except MealItemNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meal item not found"
        ) from exc


@meal_router.post("/recipe-items", status_code=status.HTTP_201_CREATED)
async def post_recipe_meal_item(
    data: RecipeMealItemCreate, user: CurrentUser, session: DatabaseSession
) -> MealItemResponse:
    try:
        return await create_recipe_meal_item(session, user.id, data)
    except RecipeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found"
        ) from exc


@meal_router.get("/days/{day_date}")
async def read_nutrition_day(
    day_date: date, user: CurrentUser, session: DatabaseSession
) -> NutritionDayResponse:
    return await get_nutrition_day(session, user.id, day_date)


# Endpoint to create a new food item for the authenticated user
@router.post("", status_code=status.HTTP_201_CREATED)
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
    try:
        await delete_food(session, user.id, food_id)
    except FoodNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=FOOD_NOT_FOUND,
        ) from exc
    except FoodInUseError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A food used in a recipe or diary cannot be deleted",
        ) from exc


# Endpoint to retrieve a food item by its ID for the authenticated user
@router.get("/{food_id}")
async def read_food(
    food_id: int,
    user: CurrentUser,
    session: DatabaseSession,
) -> FoodResponse:
    try:
        return await get_food(session, user.id, food_id)
    except FoodNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=FOOD_NOT_FOUND,
        ) from exc


# Endpoint to update a food item by its ID for the authenticated user
@router.patch("/{food_id}")
async def patch_food(
    food_id: int,
    data: FoodPatch,
    user: CurrentUser,
    session: DatabaseSession,
) -> FoodResponse:
    try:
        return await update_food(session, user.id, food_id, data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except FoodNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=FOOD_NOT_FOUND,
        ) from exc
