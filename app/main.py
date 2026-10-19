import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.health import router as health_router
from app.api.router import api_router
from app.core.auth.clerk import ClerkVerifier
from app.core.config import CorsSettings, Settings
from app.core.logging import configure_logging
from app.db.session import create_database_engine

logger = logging.getLogger("kinetix.requests")


def create_app(settings: Settings | None = None) -> FastAPI:
    cors_allowed_origins = (
        settings.cors_allowed_origins
        if settings is not None
        else CorsSettings().cors_allowed_origins
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configuration = settings if settings is not None else Settings()
        configure_logging(configuration.log_level)
        engine = create_database_engine(configuration)
        application.state.settings = configuration
        application.state.engine = engine
        application.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        application.state.clerk_verifier = ClerkVerifier(configuration)
        try:
            # Swagger's Authorize dialog must use the same scheme as the running API.
            application.openapi_schema = None
            if configuration.auth_mode == "basic":
                application.openapi()["components"]["securitySchemes"]["Authentication"] = {
                    "type": "http",
                    "scheme": "basic",
                    "description": "Local account configured in BASIC_AUTH_USERS",
                }
            yield
        finally:
            await engine.dispose()

    application = FastAPI(title="Kinetix API", version="0.1.0", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
        expose_headers=["WWW-Authenticate"],
    )
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
