from fastapi import APIRouter

from app.features.accounts.router import auth_router
from app.features.accounts.router import router as accounts_router
from app.features.goals.router import router as objective_router
from app.features.nutrition.router import (
    meal_router,
    nutrition_goal_router,
    recipe_router,
)
from app.features.nutrition.router import (
    router as nutrition_router,
)
from app.features.posts.router import router as posts_router
from app.features.social.router import friends_router, people_router
from app.features.training.router import router as training_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(accounts_router)
api_router.include_router(auth_router)
api_router.include_router(objective_router)
api_router.include_router(nutrition_router)
api_router.include_router(recipe_router)
api_router.include_router(training_router)
api_router.include_router(nutrition_goal_router)
api_router.include_router(meal_router)
api_router.include_router(posts_router)
api_router.include_router(friends_router)
api_router.include_router(people_router)
