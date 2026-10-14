from __future__ import annotations

import functools
from typing import Callable, Sequence

from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.cors import ALL_METHODS, SAFELISTED_HEADERS
from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RuntimeCORSMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        allow_origins_resolver: Callable[[], Sequence[str]],
        allow_methods: Sequence[str] = ("GET",),
        allow_headers: Sequence[str] = (),
        allow_credentials: bool = False,
        expose_headers: Sequence[str] = (),
        max_age: int = 600,
    ) -> None:
        if "*" in allow_methods:
            allow_methods = ALL_METHODS

        self.app = app
        self.allow_origins_resolver = allow_origins_resolver
        self.allow_methods = tuple(allow_methods)
        self.allow_headers = tuple(allow_headers)
        self.allow_credentials = allow_credentials
        self.expose_headers = tuple(expose_headers)
        self.max_age = max_age

    def _build_config(self) -> dict[str, object]:
        origins = tuple(dict.fromkeys(origin for origin in self.allow_origins_resolver() if origin))
        allow_all_origins = "*" in origins
        allow_all_headers = "*" in self.allow_headers
        preflight_explicit_allow_origin = not allow_all_origins or self.allow_credentials

        simple_headers: dict[str, str] = {}
        if allow_all_origins:
            simple_headers["Access-Control-Allow-Origin"] = "*"
        if self.allow_credentials:
            simple_headers["Access-Control-Allow-Credentials"] = "true"
        if self.expose_headers:
            simple_headers["Access-Control-Expose-Headers"] = ", ".join(self.expose_headers)

        preflight_headers: dict[str, str] = {}
        if preflight_explicit_allow_origin:
            preflight_headers["Vary"] = "Origin"
        else:
            preflight_headers["Access-Control-Allow-Origin"] = "*"
        preflight_headers.update(
            {
                "Access-Control-Allow-Methods": ", ".join(self.allow_methods),
                "Access-Control-Max-Age": str(self.max_age),
            }
        )

        normalized_allow_headers = sorted(SAFELISTED_HEADERS | set(self.allow_headers))
        if normalized_allow_headers and not allow_all_headers:
            preflight_headers["Access-Control-Allow-Headers"] = ", ".join(normalized_allow_headers)
        if self.allow_credentials:
            preflight_headers["Access-Control-Allow-Credentials"] = "true"

        return {
            "allow_origins": origins,
            "allow_all_origins": allow_all_origins,
            "allow_all_headers": allow_all_headers,
            "preflight_explicit_allow_origin": preflight_explicit_allow_origin,
            "simple_headers": simple_headers,
            "preflight_headers": preflight_headers,
            "allow_headers": tuple(header.lower() for header in normalized_allow_headers),
        }

    @staticmethod
    def _is_allowed_origin(origin: str, config: dict[str, object]) -> bool:
        if config["allow_all_origins"]:
            return True
        return origin in config["allow_origins"]

    def _preflight_response(self, request_headers: Headers, config: dict[str, object]) -> Response:
        requested_origin = request_headers["origin"]
        requested_method = request_headers["access-control-request-method"]
        requested_headers = request_headers.get("access-control-request-headers")

        headers = dict(config["preflight_headers"])
        failures: list[str] = []

        if self._is_allowed_origin(requested_origin, config):
            if config["preflight_explicit_allow_origin"]:
                headers["Access-Control-Allow-Origin"] = requested_origin
        else:
            failures.append("origin")

        if requested_method not in self.allow_methods:
            failures.append("method")

        if config["allow_all_headers"] and requested_headers is not None:
            headers["Access-Control-Allow-Headers"] = requested_headers
        elif requested_headers is not None:
            for header in [item.lower() for item in requested_headers.split(",")]:
                if header.strip() not in config["allow_headers"]:
                    failures.append("headers")
                    break

        if failures:
            return PlainTextResponse(
                "Disallowed CORS " + ", ".join(failures),
                status_code=400,
                headers=headers,
            )

        return PlainTextResponse("OK", status_code=200, headers=headers)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # pragma: no cover
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if origin is None:
            await self.app(scope, receive, send)
            return

        config = self._build_config()
        if scope["method"] == "OPTIONS" and "access-control-request-method" in headers:
            response = self._preflight_response(headers, config)
            await response(scope, receive, send)
            return

        send_with_cors = functools.partial(
            self._send,
            send=send,
            request_headers=headers,
            config=config,
        )
        await self.app(scope, receive, send_with_cors)

    async def _send(
        self,
        message: Message,
        send: Send,
        request_headers: Headers,
        config: dict[str, object],
    ) -> None:
        if message["type"] != "http.response.start":
            await send(message)
            return

        message.setdefault("headers", [])
        headers = MutableHeaders(scope=message)
        headers.update(config["simple_headers"])

        origin = request_headers.get("origin")
        has_cookie = "cookie" in request_headers
        if not origin:
            await send(message)
            return

        if config["allow_all_origins"] and has_cookie:
            self._allow_explicit_origin(headers, origin)
        elif not config["allow_all_origins"] and self._is_allowed_origin(origin, config):
            self._allow_explicit_origin(headers, origin)

        await send(message)

    @staticmethod
    def _allow_explicit_origin(headers: MutableHeaders, origin: str) -> None:
        headers["Access-Control-Allow-Origin"] = origin
        headers.add_vary_header("Origin")
