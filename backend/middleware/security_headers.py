"""SEC-02: Defense-in-depth security headers for backend API responses.

These headers protect against common browser attacks (MIME sniffing,
click-jacking, information leakage) even when the Caddy reverse proxy
layer is bypassed or misconfigured.  The CSP for HTML pages is
handled by the Next.js frontend middleware; this backend middleware
applies a restrictive API-oriented policy.
"""

import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# Static headers applied to every backend response.
_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "X-XSS-Protection": "0",
    "Cross-Origin-Opener-Policy": "same-origin",
    # API-only CSP: no inline scripts/styles/images, pure JSON endpoints.
    "Content-Security-Policy": (
        "default-src 'none'; " "frame-ancestors 'none'; " "base-uri 'none'"
    ),
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects browser security headers on every response."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            # Do not overwrite headers already set by route-specific logic
            # (e.g., embed endpoints may set permissive frame-ancestors).
            if header not in response.headers:
                response.headers[header] = value
        return response
