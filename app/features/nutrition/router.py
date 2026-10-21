
from fastapi import APIRouter, HTTPException, status


from app.core.auth.dependencies import CurrentUser
from app.db.session import DatabaseSession
from app.features.nutrition.schemas import FoodCreate, FoodResponse, FoodPatch
from app.features.nutrition.service import create_food, delete_food, get_food, update_food

router = APIRouter(prefix="/foods", tags=["nutrition"])


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
