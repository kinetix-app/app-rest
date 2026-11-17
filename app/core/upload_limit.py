"""Bound multipart body bytes, including chunked requests, before form parsing/spooling."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class UploadLimit:
    """Reject POST bodies above `max_bytes` for one exact route path."""

    def __init__(self, app: ASGIApp, *, path: str, max_bytes: int, detail: str):
        self.app = app
        self.path = path.rstrip("/")
        self.max_bytes = max_bytes
        self.detail = detail

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"].rstrip("/") != self.path
        ):
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_bytes:
                await JSONResponse({"detail": self.detail}, 413)(scope, receive, send)
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
