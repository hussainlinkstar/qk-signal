"""Preflight handling for the route-scoped marketing-site CORS allowance.

``core/public_site_cors.py`` (SIGNAL-1040) attaches ``Access-Control-Allow-Origin``
to individual responses. That is enough for a simple ``GET``, which needs no
preflight, but the guest audit submit is a ``POST`` with a JSON content type,
so the browser sends an ``OPTIONS`` preflight first. The global
``RuntimeCORSMiddleware`` answers every preflight it sees and rejects the
marketing-site origin with 400, because that origin is deliberately absent
from the credentialed ``CORS_ORIGINS`` allowlist. The route level ``OPTIONS``
handler is therefore never reached.

This middleware sits outside the global one and handles only the narrow case:
a preflight for a path under ``/api/v1/public/`` from an origin configured in
``PUBLIC_SITE_ORIGINS``. Everything else is passed straight through and still
answered by the global middleware exactly as before.

On the response path it also strips ``Access-Control-Allow-Credentials`` from
these routes. The global middleware sets that header for any request carrying
an ``Origin``, and this allowance is explicitly uncredentialed: the marketing
site must never be able to make a cookie-bearing cross-origin call into
Signal, which is the whole reason its origin is kept out of ``CORS_ORIGINS``.
"""

from __future__ import annotations

import functools
from typing import Final

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.public_site_cors import is_public_site_origin

PUBLIC_PATH_PREFIX: Final[str] = "/api/v1/public/"
ALLOWED_METHODS: Final[str] = "GET, POST, OPTIONS"
ALLOWED_HEADERS: Final[str] = "content-type"
MAX_AGE_SECONDS: Final[int] = 600


class PublicSiteCorsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # pragma: no cover - websockets are untouched
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith(PUBLIC_PATH_PREFIX):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if not is_public_site_origin(origin):
            await self.app(scope, receive, send)
            return

        if scope.get("method") == "OPTIONS" and "access-control-request-method" in headers:
            response = Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": ALLOWED_METHODS,
                    "Access-Control-Allow-Headers": ALLOWED_HEADERS,
                    "Access-Control-Max-Age": str(MAX_AGE_SECONDS),
                    "Vary": "Origin",
                },
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, functools.partial(self._send, send=send, origin=origin))

    @staticmethod
    async def _send(message: Message, send: Send, origin: str) -> None:
        if message["type"] == "http.response.start":
            headers = MutableHeaders(scope=message)
            # Applied here rather than per route so that a rejected request
            # is readable too. A 400 or a 429 without this header is an opaque
            # network error in the browser, and the visitor sees nothing at
            # all instead of the reason their audit was refused.
            headers["Access-Control-Allow-Origin"] = origin
            headers.add_vary_header("Origin")
            # Starlette's __delitem__ is a no-op when the header is absent.
            del headers["access-control-allow-credentials"]
        await send(message)
