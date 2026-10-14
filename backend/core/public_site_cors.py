"""Route-scoped CORS allowance for the public marketing site.

The global ``RuntimeCORSMiddleware`` allowlist is credentialed: every origin in
it may send cookie-bearing requests to every Signal endpoint, so adding the
marketing site there would turn an XSS on that site into an authenticated
pivot into Signal. The site only needs to read one unauthenticated JSON
document, so it gets a separate, narrower allowance that is applied per route
and grants no credentials of its own.

Origins come from ``PUBLIC_SITE_ORIGINS`` (comma separated, DB-backed runtime
config with an environment default), so they are environment specific and never
hardcoded:

* preprod needs a value, because the site (``https://www.preprod.qiko.ai``) and
  Signal (``https://signal.preprod.qiko.ai``) are different origins;
* live needs nothing, because the site is path shared on ``https://qiko.ai``,
  which is the same origin as the API, and the apex/www pair is already covered
  by the global allowlist derived from ``DOMAIN``.

A wildcard is refused even if one is configured: this allowance is only ever an
explicit list.
"""

from __future__ import annotations

from typing import Sequence

from core.config import settings


def resolve_public_site_origins() -> tuple[str, ...]:
    """Return the configured marketing-site origins, wildcards removed."""
    try:
        configured: Sequence[str] = settings.public_site_origins
    except Exception:  # pragma: no cover - configuration lookup must never 500
        return ()

    origins: list[str] = []
    for candidate in configured:
        normalized = str(candidate).strip().rstrip("/")
        if not normalized or normalized == "*":
            continue
        if normalized not in origins:
            origins.append(normalized)
    return tuple(origins)


def is_public_site_origin(origin: str | None) -> bool:
    if not origin:
        return False
    return origin.strip().rstrip("/") in resolve_public_site_origins()


def _mark_origin_dependent(response) -> None:
    existing = response.headers.get("vary")
    if not existing:
        response.headers["Vary"] = "Origin"
        return
    if "origin" in [item.strip().lower() for item in existing.split(",")]:
        return
    response.headers["Vary"] = f"{existing}, Origin"


def apply_public_site_cors(request, response) -> bool:
    """Allow *response* to be read by a configured marketing-site origin.

    Returns whether the allowance was granted. A request with no ``Origin``
    (server-side fetch, curl) and a request from an origin that is not
    configured both come back without an ``Access-Control-Allow-Origin``
    header, so a browser on a disallowed origin cannot read the response.
    """
    # The response body depends on Origin only through this header, but it is
    # publicly cacheable, so shared caches must key on Origin regardless.
    _mark_origin_dependent(response)

    origin = request.headers.get("origin") if request is not None else None
    if not is_public_site_origin(origin):
        return False

    response.headers["Access-Control-Allow-Origin"] = origin
    return True
