from fastapi import APIRouter

from app.features.accounts.router import auth_router
from app.features.accounts.router import router as accounts_router
from app.features.goals.router import router as objective_router
from app.features.leagues.results_router import router as league_results_router
from app.features.leagues.router import invitation_router
from app.features.leagues.router import router as leagues_router
from app.features.leagues.standings_router import router as league_standings_router
from app.features.nutrition.router import (
    meal_router,
    nutrition_goal_router,
    recipe_router,
)
from app.features.nutrition.router import (
    router as nutrition_router,
)
from app.features.training.router import router as training_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(leagues_router)
api_router.include_router(league_results_router)
api_router.include_router(league_standings_router)
api_router.include_router(invitation_router)
api_router.include_router(accounts_router)
api_router.include_router(auth_router)
api_router.include_router(objective_router)
api_router.include_router(nutrition_router)
api_router.include_router(recipe_router)
api_router.include_router(training_router)
api_router.include_router(nutrition_goal_router)
api_router.include_router(meal_router)
