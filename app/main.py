import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.security.http import HTTPBase
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.health import router as health_router
from app.api.router import api_router
from app.core.auth.clerk import ClerkVerifier
from app.core.config import Settings
from app.core.logging import configure_logging
from app.core.storage.azure import BlobStorage
from app.db.session import create_database_engine
from app.features.accounts.upload_limit import ProfileUploadLimit

logger = logging.getLogger("kinetix.requests")


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configure_logging(configuration.log_level)
        engine = create_database_engine(configuration)
        application.state.settings = configuration
        application.state.engine = engine
        application.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        application.state.clerk_verifier = ClerkVerifier(configuration)
        application.state.blob_storage = None
        try:
            if configuration.azure_storage_account_url:
                application.state.blob_storage = BlobStorage(configuration)
            yield
        finally:
            try:
                if application.state.blob_storage is not None:
                    await application.state.blob_storage.close()
            finally:
                await engine.dispose()

    application = FastAPI(title="Kinetix API", version="0.1.0", lifespan=lifespan)
    application.add_middleware(ProfileUploadLimit)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=configuration.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
        expose_headers=["WWW-Authenticate"],
    )
    application.include_router(health_router)
    # Declare the selected HTTP scheme for business routes. CurrentUser validates
    # the raw credentials, including UTF-8 Basic passwords and Clerk session claims.
    authentication = HTTPBase(
        scheme="basic" if configuration.auth_mode == "basic" else "bearer",
        scheme_name="Authentication",
        description=(
            "Local account configured in BASIC_AUTH_USERS"
            if configuration.auth_mode == "basic"
            else "Clerk session token"
        ),
        auto_error=False,
    )
    application.include_router(api_router, dependencies=[Depends(authentication)])

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
