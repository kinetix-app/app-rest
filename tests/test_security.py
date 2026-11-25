from typing import Annotated

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI, File, Request, UploadFile
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.core.security import NUL_DETAIL, RejectNulCharacters, database_busy
from app.main import create_app


def echo_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RejectNulCharacters)
    app.add_exception_handler(PoolTimeoutError, database_busy)

    @app.get("/items")
    async def search(name: str = "") -> dict[str, str]:
        return {"name": name}

    @app.post("/items")
    async def create(request: Request) -> dict[str, object]:
        return {"received": await request.json()}

    @app.post("/upload")
    async def upload(file: Annotated[UploadFile, File()]) -> dict[str, int]:
        return {"size": len(await file.read())}

    @app.get("/busy")
    async def busy() -> None:
        raise PoolTimeoutError("QueuePool limit reached")

    return app


async def call(app: FastAPI, method: str, url: str, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, url, **kwargs)


@pytest.mark.anyio
@pytest.mark.parametrize("url", ["/items?name=%00", "/items?name=a%00b", "/items%00"])
async def test_nul_in_path_or_query_is_rejected_as_invalid_input(url):
    response = await call(echo_app(), "GET", url)
    assert response.status_code == 422
    assert response.json() == {"detail": NUL_DETAIL}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "body",
    [
        b'{"name": "a\\u0000b"}',
        b'{"tags": ["ok", "\\u0000"]}',
        b'{"nested": {"\\u0000key": 1}}',
    ],
)
async def test_nul_in_json_body_is_rejected(body):
    response = await call(
        echo_app(), "POST", "/items", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json() == {"detail": NUL_DETAIL}


@pytest.mark.anyio
async def test_valid_requests_pass_through_unchanged():
    app = echo_app()
    search = await call(app, "GET", "/items?name=caf%C3%A9+latte")
    # An escaped backslash followed by "u0000" is ordinary text, not a NUL character.
    created = await call(
        app,
        "POST",
        "/items",
        content=b'{"name": "\\\\u0000", "kcal": 10}',
        headers={"Content-Type": "application/json"},
    )
    upload = await call(app, "POST", "/upload", files={"file": ("a.bin", b"\x00\x01\x00")})
    assert search.json() == {"name": "café latte"}
    assert created.status_code == 200
    assert created.json() == {"received": {"name": "\\u0000", "kcal": 10}}
    assert upload.json() == {"size": 3}


@pytest.mark.anyio
async def test_exhausted_connection_pool_returns_retryable_503():
    response = await call(echo_app(), "GET", "/busy")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "2"


@pytest.mark.anyio
@pytest.mark.parametrize(("env", "hsts"), [("development", False), ("production", True)])
async def test_api_responses_carry_security_headers(settings, env, hsts):
    settings.app_env = env
    if env == "production":
        settings.auth_mode = "clerk"
    app = create_app(settings)
    async with LifespanManager(app):
        live = await call(app, "GET", "/health/live")
        nul = await call(app, "GET", "/api/v1/routines?name=%00")
    for response in (live, nul):
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Cross-Origin-Resource-Policy"] == "same-origin"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert ("Strict-Transport-Security" in response.headers) is hsts
    assert nul.status_code == 422
