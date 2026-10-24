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
)
from app.features.nutrition.service import (
    create_food,
    create_meal_item,
    create_nutrition_goal,
    delete_food,
    get_food,
    get_nutrition_day,
    get_nutrition_goal,
    search_foods,
    update_food,
    update_nutrition_goal,
)

router = APIRouter(prefix="/foods", tags=["nutrition"])

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
    name: str = Query(min_length=1, max_length=150),
) -> list[FoodResponse]:
    return await search_foods(session, user.id, name)


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

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Food not found",
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
