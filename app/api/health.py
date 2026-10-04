import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: str


@router.get("/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "Database unavailable"}},
)
async def readiness(request: Request) -> HealthResponse | JSONResponse:
    try:
        async with asyncio.timeout(request.app.state.settings.database_timeout_seconds):
            async with request.app.state.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except TimeoutError, SQLAlchemyError, OSError:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return HealthResponse(status="ok")
