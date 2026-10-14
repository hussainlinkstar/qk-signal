"""Live check of the Bing Webmaster integration (SIGV2-1265).

Answers the one question no mock can: does a real Bing account return rows
for a real site, and does our own parsing handle the payload Bing actually
sends? It calls the three stat endpoints through the same helpers the product
uses, so a change in Bing's response shape fails here rather than in
production.

Credentials come from the environment and are never printed:

    BING_WEBMASTER_API_KEY=...     # Bing Webmaster Tools -> Settings -> API access
    # or, to exercise the OAuth path the product actually uses:
    BING_WEBMASTER_ACCESS_TOKEN=...

Usage:
    python scripts/check_bing_webmaster.py                 # list the account's sites
    python scripts/check_bing_webmaster.py https://qiko.ai/   # and pull that site's stats

Read-only: it fetches and parses, and writes nothing to the database.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

backend_path = Path(__file__).parent.parent / "backend"
if not backend_path.exists():
    backend_path = Path("/app")
sys.path.insert(0, str(backend_path))

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DISABLE_TRACING", "1")

import httpx  # noqa: E402

from app.services.bing_webmaster_service import (  # noqa: E402
    BING_API_BASE,
    BingWebmasterService,
    covered_period,
    normalize_stats_row,
)

API_KEY = (os.getenv("BING_WEBMASTER_API_KEY") or "").strip()
ACCESS_TOKEN = (os.getenv("BING_WEBMASTER_ACCESS_TOKEN") or "").strip()


class ApiKeyService(BingWebmasterService):
    """Same parsing, authenticated with an API key instead of a bearer token.

    The product authenticates with OAuth. The API key path exists here because
    it needs no browser round trip, which makes it the quickest way to confirm
    account access and response shape.
    """

    def __init__(self, api_key: str) -> None:
        super().__init__(access_token="")
        self._api_key = api_key

    def _get(self, path: str, params: dict) -> object:
        query = {**params, "apikey": self._api_key}
        with httpx.Client(timeout=20.0) as client:
            response = client.get(f"{BING_API_BASE}/{path}", params=query)
        if response.status_code >= 400:
            raise SystemExit(f"{path}: HTTP {response.status_code}")
        payload = response.json() if response.content else {}
        if isinstance(payload, dict) and payload.get("ErrorCode"):
            # Bing answers 200 with an error body; the message names the fault
            # but never echoes the credential.
            raise SystemExit(f"{path}: {payload.get('Message')}")
        return payload


def _service() -> BingWebmasterService:
    if ACCESS_TOKEN:
        print("auth: OAuth bearer token (the path the product uses)")
        return BingWebmasterService(access_token=ACCESS_TOKEN)
    if API_KEY:
        print("auth: API key")
        return ApiKeyService(API_KEY)
    raise SystemExit("no credentials. Set BING_WEBMASTER_API_KEY or BING_WEBMASTER_ACCESS_TOKEN.")


def _report(label: str, rows: list[dict], dimension_key: str | None) -> None:
    parsed = [row for row in (normalize_stats_row(raw) for raw in rows) if row is not None]
    period = covered_period(parsed)
    print(f"\n{label}: {len(rows)} rows from Bing, {len(parsed)} parsed by our normalizer")
    print(f"  period actually covered: {period['start']} to {period['end']}")
    print(f"  clicks {sum(r['clicks'] for r in parsed):.0f}", end="")
    print(f", impressions {sum(r['impressions'] for r in parsed):.0f}")
    if len(parsed) < len(rows):
        print(f"  WARNING: {len(rows) - len(parsed)} rows could not be dated and were dropped")
    if dimension_key and rows:
        sample = [str(raw.get(dimension_key) or "")[:60] for raw in rows[:3]]
        print(f"  sample {dimension_key}: {sample}")


def main() -> None:
    service = _service()
    sites = service.get_user_sites()
    print(f"\nsites visible to this account: {len(sites)}")
    for site in sites:
        print(f"  {site}")
    if not sites:
        raise SystemExit("the account sees no verified sites, so no binding can ever ingest")

    target = sys.argv[1] if len(sys.argv) > 1 else None
    if target is None:
        print("\npass a site URL as the first argument to pull its stats")
        return
    if target not in sites:
        raise SystemExit(
            f"{target} is not in this account's site list; the product refuses it for the "
            "same reason (site_not_owned)"
        )

    _report("site stats", service.get_rank_and_traffic_stats(target), None)
    _report("query stats", service.get_query_stats(target), "Query")
    _report("page stats", service.get_page_stats(target), "Url")
    print("\nposition stays unavailable by contract: Bing never documented the scale.")


if __name__ == "__main__":
    main()
