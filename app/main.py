import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.health import router as health_router
from app.api.router import api_router
from app.core.config import Settings
from app.core.logging import configure_logging
from app.db.session import create_database_engine

logger = logging.getLogger("kinetix.requests")


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configuration = settings if settings is not None else Settings()
        configure_logging(configuration.log_level)
        engine = create_database_engine(configuration)
        application.state.settings = configuration
        application.state.engine = engine
        application.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            yield
        finally:
            await engine.dispose()

    application = FastAPI(title="Kinetix API", version="0.1.0", lifespan=lifespan)
    application.include_router(health_router)
    application.include_router(api_router)

    @application.middleware("http")
    async def log_request(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = uuid4().hex
        started = perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        route = getattr(request.scope.get("route"), "path", "unmatched")
        logger.info(
            "method=%s route=%s status=%d duration_ms=%.2f request_id=%s",
            request.method,
            route,
            response.status_code,
            (perf_counter() - started) * 1000,
            request_id,
        )
        return response

    return application


app = create_app()
