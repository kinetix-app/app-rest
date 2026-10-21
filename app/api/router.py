from fastapi import APIRouter

from app.features.accounts.router import router as accounts_router
from app.features.nutrition.router import router as nutrition_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(accounts_router)
api_router.include_router(nutrition_router)

