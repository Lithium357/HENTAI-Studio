"""Only transport policy lives here; routing and validation belong to FastAPI."""

import asyncio

from starlette.types import ASGIApp, Receive, Scope, Send

from .errors import error_response


class RequestLimits:
    def __init__(self, app: ASGIApp, max_bytes: int = 131_072, timeout: float = 15):
        self.app, self.max_bytes, self.timeout = app, max_bytes, timeout

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or scope["method"] in {"GET", "HEAD", "OPTIONS"}:
            return await self.app(scope, receive, send)
        lengths = [value for key, value in scope["headers"] if key == b"content-length"]
        if lengths and (len(lengths) != 1 or not lengths[0].isdigit()):
            return await error_response(
                400,
                "invalid_content_length",
                "Content-Length must be a nonnegative integer.",
            )(scope, receive, send)
        if lengths and int(lengths[0]) > self.max_bytes:
            return await error_response(
                413, "request_too_large", "The request body exceeds 128 KiB."
            )(scope, receive, send)
        body = bytearray()
        try:
            async with asyncio.timeout(self.timeout):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    body.extend(message.get("body", b""))
                    if len(body) > self.max_bytes:
                        return await error_response(
                            413,
                            "request_too_large",
                            "The request body exceeds 128 KiB.",
                        )(scope, receive, send)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            return await error_response(
                408, "request_timeout", "The request body was not received in time."
            )(scope, receive, send)
        if lengths and len(body) != int(lengths[0]):
            return await error_response(
                400, "incomplete_body", "The body length does not match Content-Length."
            )(scope, receive, send)
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)


class ResponseHeaders:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        async def send_response(message):
            if message["type"] == "http.response.start":
                message["headers"] = [
                    *message.get("headers", []),
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                ]
            await send(message)

        await self.app(scope, receive, send_response)


class LocalRequests:
    """Reject foreign origins and DNS-rebinding hosts on this command-executing API."""

    def __init__(self, app: ASGIApp, hosts: list[str]):
        self.app = app
        self.hosts = {host.lower() for host in hosts}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        from urllib.parse import urlsplit

        headers = {
            key.lower(): value.decode("latin-1") for key, value in scope["headers"]
        }
        host = headers.get(b"host", "")
        try:
            hostname = urlsplit("//" + host).hostname
            origin = headers.get(b"origin")
            foreign = origin is not None and origin != f"{scope['scheme']}://{host}"
        except ValueError:
            hostname, foreign = None, True
        if hostname not in self.hosts or foreign:
            return await error_response(
                403,
                "untrusted_request",
                "Use Studio through its configured local address.",
            )(scope, receive, send)
        return await self.app(scope, receive, send)
