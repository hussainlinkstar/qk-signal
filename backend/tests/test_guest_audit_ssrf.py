"""SSRF coverage for the unauthenticated guest audit path.

The guest path takes a URL from the public internet and makes Signal fetch
it, so it is the highest value SSRF target in the product. Two properties are
asserted here, and the second is the one that is usually missed: a target
that is public at validation time but *redirects* into a private range must
be blocked at the redirect, not just at submission.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import httpx
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services import url_validation  # noqa: E402
from services.scraper import ScraperService  # noqa: E402
from services.url_validation import (  # noqa: E402
    SSRFBlockedError,
    normalize_and_validate_url,
    safe_async_fetch,
)

PRIVATE_REDIRECT_TARGETS = [
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    "http://127.0.0.1:8000/api/v1/admin/users",
    "http://10.0.0.5/",
    "http://192.168.0.10/",
    "http://172.16.0.9/",
    "http://[::1]/",
]


def _install_mock_transport(monkeypatch, handler):
    """Point ``safe_async_fetch`` at a mock transport.

    ``safe_async_fetch`` builds its own ``AsyncClient``, so the client class
    is swapped rather than the transport, keeping the redirect loop and the
    validation calls under test exactly as they run in production.
    """
    real_client = httpx.AsyncClient

    def _factory(**kwargs):
        kwargs.pop("http2", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(url_validation.httpx, "AsyncClient", _factory)


# ---------------------------------------------------------------------------
# Direct private targets
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blocked", PRIVATE_REDIRECT_TARGETS)
def test_private_and_link_local_targets_are_rejected_before_any_request(blocked):
    with pytest.raises(ValueError):
        normalize_and_validate_url(blocked)


@pytest.mark.asyncio
async def test_safe_async_fetch_refuses_a_private_target(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError(f"a request was made to {request.url}")

    _install_mock_transport(monkeypatch, handler)

    with pytest.raises(SSRFBlockedError):
        await safe_async_fetch("http://169.254.169.254/latest/meta-data/")


def test_a_hostname_resolving_to_a_private_address_is_rejected(monkeypatch):
    """The DNS answer is checked, not just the literal in the URL."""

    def fake_getaddrinfo(host, port, type):
        _ = host, port, type
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))]

    monkeypatch.setattr(url_validation.socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(ValueError):
        normalize_and_validate_url("http://metadata.attacker.example")


# ---------------------------------------------------------------------------
# The redirect case
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("private_target", PRIVATE_REDIRECT_TARGETS)
async def test_a_public_url_redirecting_into_a_private_range_is_blocked(
    monkeypatch, private_target
):
    """The classic bypass: pass validation with a public host, then 302.

    The host is public and resolvable, so submission succeeds. If only the
    submitted URL were validated, Signal would follow the redirect and fetch
    the private target on the attacker's behalf.
    """
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.host)
        if request.url.host == "public.example.com":
            return httpx.Response(302, headers={"location": private_target})
        raise AssertionError(f"followed the redirect to {request.url}")

    _install_mock_transport(monkeypatch, handler)

    with pytest.raises(SSRFBlockedError):
        await safe_async_fetch("https://public.example.com/")

    # Exactly one request, to the public host. The private hop never happened.
    assert requested == ["public.example.com"]


@pytest.mark.asyncio
async def test_a_redirect_chain_is_validated_at_every_hop(monkeypatch):
    """Two public hops then a private one still has to be caught."""
    hops = {
        "public.example.com": "https://second.example.com/",
        "second.example.com": "https://third.example.com/",
        "third.example.com": "http://127.0.0.1:8000/internal",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        location = hops.get(request.url.host)
        if location:
            return httpx.Response(302, headers={"location": location})
        raise AssertionError(f"followed the redirect to {request.url}")

    _install_mock_transport(monkeypatch, handler)

    with pytest.raises(SSRFBlockedError):
        await safe_async_fetch("https://public.example.com/")


@pytest.mark.asyncio
async def test_a_relative_redirect_into_a_private_host_is_blocked(monkeypatch):
    """A ``Location`` without a scheme is resolved and then revalidated."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "public.example.com":
            return httpx.Response(302, headers={"location": "//127.0.0.1/internal"})
        raise AssertionError(f"followed the redirect to {request.url}")

    _install_mock_transport(monkeypatch, handler)

    with pytest.raises(SSRFBlockedError):
        await safe_async_fetch("https://public.example.com/")


@pytest.mark.asyncio
async def test_a_redirect_between_public_hosts_is_still_followed(monkeypatch):
    """The guard must not break ordinary apex to www redirects."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.com":
            return httpx.Response(301, headers={"location": "https://www.example.com/"})
        return httpx.Response(200, text="<html><title>ok</title></html>")

    _install_mock_transport(monkeypatch, handler)

    response = await safe_async_fetch("https://example.com/")

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# The guest audit collectors specifically
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_guest_fallback_scraper_does_not_follow_a_private_redirect(monkeypatch):
    """The fallback scraper is the collector the guest path relies on today,
    because Firecrawl credits are exhausted, so it is the one that matters."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "public.example.com":
            return httpx.Response(
                302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
            )
        raise AssertionError(f"followed the redirect to {request.url}")

    _install_mock_transport(monkeypatch, handler)

    result = await ScraperService()._fallback_scrape("https://public.example.com/")

    assert result["success_status"] is False
    assert "markdown_content" not in result


@pytest.mark.asyncio
async def test_the_network_analyzer_does_not_follow_a_private_redirect(monkeypatch):
    from services.network_analyzer import NetworkAnalysisService

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "public.example.com":
            return httpx.Response(302, headers={"location": "http://10.0.0.5/"})
        raise AssertionError(f"followed the redirect to {request.url}")

    _install_mock_transport(monkeypatch, handler)

    result = await NetworkAnalysisService().analyze_network_protocols("https://public.example.com/")

    # It degrades to "unknown" rather than reaching the private host.
    assert result["http_version"] == "Unknown"
    assert result["supports_http2"] is False
