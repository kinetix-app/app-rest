"""HTTP hardening found through the OWASP ZAP API scan.

- `SecurityHeaders` adds browser security headers to every response.
- `RejectNulCharacters` answers 422 before a NUL character reaches PostgreSQL,
  which cannot store it in text columns and would otherwise fail with a 500.
- `database_busy` turns connection-pool exhaustion into a retryable 503.
"""

import json
from typing import Any
from urllib.parse import unquote_to_bytes

from fastapi import Request
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

NUL_DETAIL = "Text values must not contain NUL (0x00) characters"
BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})
JSON_NUL_ESCAPE = b"\\u0000"


class SecurityHeaders:
    """Set defensive response headers; HSTS only where the API is served over HTTPS."""

    def __init__(self, app: ASGIApp, *, hsts: bool):
        self.app = app
        self.headers = {
            "X-Content-Type-Options": "nosniff",
            "Cross-Origin-Resource-Policy": "same-origin",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
        }
        if hsts:
            self.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self.headers.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _contains_nul(value: Any) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(_contains_nul(key) or _contains_nul(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_nul(item) for item in value)
    return False


def _is_json(scope: Scope) -> bool:
    for name, value in scope.get("headers", []):
        if name == b"content-type":
            media_type = value.split(b";", 1)[0].strip().lower()
            return media_type == b"application/json" or media_type.endswith(b"+json")
    return False


class RejectNulCharacters:
    """Reject NUL in the path, query string or JSON body; binary uploads are untouched."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        reject = JSONResponse({"detail": NUL_DETAIL}, 422)
        raw_path = scope.get("raw_path") or scope["path"].encode()
        if b"\x00" in unquote_to_bytes(raw_path) or b"\x00" in unquote_to_bytes(
            scope.get("query_string", b"").replace(b"+", b" ")
        ):
            await reject(scope, receive, send)
            return
        if scope["method"] not in BODY_METHODS or not _is_json(scope):
            await self.app(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break
        # Parse only when an escape may be present; malformed JSON is left to FastAPI.
        if JSON_NUL_ESCAPE in body.lower():
            try:
                if _contains_nul(json.loads(body)):
                    await reject(scope, receive, send)
                    return
            except ValueError:
                pass

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


async def database_busy(_request: Request, _error: Exception) -> JSONResponse:
    """All pooled connections stayed busy for the configured timeout."""
    return JSONResponse(
        {"detail": "The service is busy, please retry shortly"},
        503,
        headers={"Retry-After": "2"},
    )
