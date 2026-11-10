"""Bound multipart body bytes, including chunked requests, before form parsing/spooling."""

import re

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.features.training.creation import MAX_ROUTINE_REQUEST_BYTES

# 5MiB file plus bounded multipart headers/fields.
MAX_PICTURE_REQUEST_BYTES = 5 * 1024 * 1024 + 64 * 1024


def _request_limit(scope: Scope) -> int | None:
    if scope["type"] != "http" or scope["method"] != "POST":
        return None
    path = scope["path"].rstrip("/")
    if path == "/api/v1/routines":
        return MAX_ROUTINE_REQUEST_BYTES
    if path == "/api/v1/me/profile/picture" or re.fullmatch(
        r"/api/v1/routines/\d+/picture/?", scope["path"], flags=re.ASCII
    ):
        return MAX_PICTURE_REQUEST_BYTES
    return None


class ProfileUploadLimit:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = _request_limit(scope)
        if limit is None:
            await self.app(scope, receive, send)
            return
        is_create = scope["path"].rstrip("/") == "/api/v1/routines"
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > limit:
                detail = (
                    "Routine request exceeds 21 MiB limit"
                    if is_create
                    else "Picture exceeds 5 MiB limit"
                )
                await JSONResponse({"detail": detail}, 413)(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        sent = False

        async def bounded_receive() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
