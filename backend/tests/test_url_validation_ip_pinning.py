"""DNS-rebinding (TOCTOU) protection for the SSRF-safe fetch helpers.

SIGV2-1247: ``_validate_host`` resolved the hostname and checked the resolved
IPs, but the request was then issued against the hostname, so the resolver was
free to return a private address on the second lookup. These tests pin the
connection to the address set that validation approved.
"""

import socket
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

import httpx
import pytest

from services.url_validation import (
    SSRFBlockedError,
    async_request_with_validation,
    safe_async_fetch,
    safe_sync_fetch,
    sync_request_with_validation,
)

PUBLIC_IP = "93.184.216.34"
PUBLIC_IP_ALT = "93.184.216.35"
PUBLIC_IP_HOP = "8.8.4.4"
PRIVATE_IP = "10.1.2.3"
METADATA_IP = "169.254.169.254"


class _RebindingResolver:
    """``getaddrinfo`` stub whose answer changes between lookups.

    *answers* maps a hostname to a list of rounds; every lookup consumes the
    next round and the final round is reused for any further lookup.
    """

    def __init__(self, answers: dict[str, list[list[str]]]):
        self._answers = {host: list(rounds) for host, rounds in answers.items()}
        self.lookups: list[str] = []

    def __call__(self, host, port=None, *args, **kwargs):
        self.lookups.append(host)
        rounds = self._answers.get(host)
        if not rounds:
            raise socket.gaierror(f"no stub answer for {host}")
        ips = rounds[0] if len(rounds) == 1 else rounds.pop(0)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0)) for ip in ips]


def _ok_response(content: bytes = b"ok", status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, content=content)


def _redirect_response(location: str, status_code: int = 302) -> httpx.Response:
    return httpx.Response(status_code, headers={"location": location})


def _requested_urls(mock_request) -> list[httpx.URL]:
    return [httpx.URL(str(call.args[1])) for call in mock_request.call_args_list]


def _request_kwargs(mock_request, index: int = 0) -> dict:
    return mock_request.call_args_list[index].kwargs


def _header(kwargs: dict, name: str) -> str | None:
    headers = kwargs.get("headers") or {}
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


# ---------------------------------------------------------------------------
# safe_async_fetch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_fetch_connects_to_validated_ip_not_the_rebound_one():
    resolver = _RebindingResolver({"rebinding.example.com": [[PUBLIC_IP], [PRIVATE_IP]]})
    with patch("services.url_validation.socket.getaddrinfo", resolver):
        with patch("services.url_validation.httpx.AsyncClient") as mock_cls:
            client = mock_cls.return_value.__aenter__.return_value
            client.request.return_value = _ok_response()
            await safe_async_fetch("https://rebinding.example.com/data")

    urls = _requested_urls(client.request)
    assert len(urls) == 1
    assert urls[0].host == PUBLIC_IP
    assert urls[0].path == "/data"
    assert PRIVATE_IP not in {url.host for url in urls}


@pytest.mark.asyncio
async def test_async_fetch_keeps_host_header_and_tls_sni_on_the_real_hostname():
    resolver = _RebindingResolver({"pinned.example.com": [[PUBLIC_IP], [METADATA_IP]]})
    with patch("services.url_validation.socket.getaddrinfo", resolver):
        with patch("services.url_validation.httpx.AsyncClient") as mock_cls:
            client = mock_cls.return_value.__aenter__.return_value
            client.request.return_value = _ok_response()
            await safe_async_fetch("https://pinned.example.com/page")

    kwargs = _request_kwargs(client.request)
    assert _header(kwargs, "Host") == "pinned.example.com"
    assert kwargs.get("extensions", {}).get("sni_hostname") == "pinned.example.com"


@pytest.mark.asyncio
async def test_async_fetch_pins_a_non_default_port_and_keeps_it_in_the_host_header():
    resolver = _RebindingResolver({"ported.example.com": [[PUBLIC_IP], [PRIVATE_IP]]})
    with patch("services.url_validation.socket.getaddrinfo", resolver):
        with patch("services.url_validation.httpx.AsyncClient") as mock_cls:
            client = mock_cls.return_value.__aenter__.return_value
            client.request.return_value = _ok_response()
            await safe_async_fetch("https://ported.example.com:8443/x")

    url = _requested_urls(client.request)[0]
    assert url.host == PUBLIC_IP
    assert url.port == 8443
    assert _header(_request_kwargs(client.request), "Host") == "ported.example.com:8443"


@pytest.mark.asyncio
async def test_async_fetch_pins_every_redirect_hop_independently():
    resolver = _RebindingResolver(
        {
            "start.example.com": [[PUBLIC_IP], [PRIVATE_IP]],
            "hop.example.com": [[PUBLIC_IP_HOP], [PRIVATE_IP]],
        }
    )
    with patch("services.url_validation.socket.getaddrinfo", resolver):
        with patch("services.url_validation.httpx.AsyncClient") as mock_cls:
            client = mock_cls.return_value.__aenter__.return_value
            client.request.side_effect = [
                _redirect_response("https://hop.example.com/final"),
                _ok_response(b"final"),
            ]
            response = await safe_async_fetch("https://start.example.com/")

    assert response.content == b"final"
    hosts = [url.host for url in _requested_urls(client.request)]
    assert hosts == [PUBLIC_IP, PUBLIC_IP_HOP]
    assert _header(_request_kwargs(client.request, 1), "Host") == "hop.example.com"


@pytest.mark.asyncio
async def test_async_fetch_still_blocks_a_host_that_resolves_private_at_validation():
    resolver = _RebindingResolver({"evil.example.com": [[PRIVATE_IP]]})
    with patch("services.url_validation.socket.getaddrinfo", resolver):
        with pytest.raises(SSRFBlockedError, match="Private or reserved"):
            await safe_async_fetch("https://evil.example.com/")


@pytest.mark.asyncio
async def test_async_fetch_falls_back_to_the_next_validated_ip_on_connect_failure():
    resolver = _RebindingResolver({"multi.example.com": [[PUBLIC_IP, PUBLIC_IP_ALT]]})
    with patch("services.url_validation.socket.getaddrinfo", resolver):
        with patch("services.url_validation.httpx.AsyncClient") as mock_cls:
            client = mock_cls.return_value.__aenter__.return_value
            client.request.side_effect = [
                httpx.ConnectError("refused"),
                _ok_response(b"second"),
            ]
            response = await safe_async_fetch("https://multi.example.com/")

    assert response.content == b"second"
    assert [url.host for url in _requested_urls(client.request)] == [
        PUBLIC_IP,
        PUBLIC_IP_ALT,
    ]


@pytest.mark.asyncio
async def test_async_fetch_leaves_an_ip_literal_target_untouched():
    with patch("services.url_validation.httpx.AsyncClient") as mock_cls:
        client = mock_cls.return_value.__aenter__.return_value
        client.request.return_value = _ok_response()
        await safe_async_fetch(f"https://{PUBLIC_IP}/direct")

    url = _requested_urls(client.request)[0]
    assert url.host == PUBLIC_IP
    assert _header(_request_kwargs(client.request), "Host") is None


@pytest.mark.asyncio
async def test_async_fetch_connects_by_hostname_when_resolution_yields_nothing():
    def failing_resolver(host, port=None, *args, **kwargs):
        raise socket.gaierror("temporary failure in name resolution")

    with patch("services.url_validation.socket.getaddrinfo", failing_resolver):
        with patch("services.url_validation.httpx.AsyncClient") as mock_cls:
            client = mock_cls.return_value.__aenter__.return_value
            client.request.return_value = _ok_response()
            await safe_async_fetch("https://unresolvable.example.com/")

    assert _requested_urls(client.request)[0].host == "unresolvable.example.com"


# ---------------------------------------------------------------------------
# safe_sync_fetch
# ---------------------------------------------------------------------------


def test_sync_fetch_connects_to_validated_ip_not_the_rebound_one():
    resolver = _RebindingResolver({"rebinding.example.com": [[PUBLIC_IP], [METADATA_IP]]})
    with patch("services.url_validation.socket.getaddrinfo", resolver):
        with patch("services.url_validation.httpx.Client") as mock_cls:
            client = mock_cls.return_value.__enter__.return_value
            client.request.return_value = _ok_response()
            safe_sync_fetch("https://rebinding.example.com/data")

    urls = _requested_urls(client.request)
    assert [url.host for url in urls] == [PUBLIC_IP]
    kwargs = _request_kwargs(client.request)
    assert _header(kwargs, "Host") == "rebinding.example.com"
    assert kwargs.get("extensions", {}).get("sni_hostname") == "rebinding.example.com"


def test_sync_fetch_pins_every_redirect_hop_independently():
    resolver = _RebindingResolver(
        {
            "start.example.com": [[PUBLIC_IP], [PRIVATE_IP]],
            "hop.example.com": [[PUBLIC_IP_HOP], [PRIVATE_IP]],
        }
    )
    with patch("services.url_validation.socket.getaddrinfo", resolver):
        with patch("services.url_validation.httpx.Client") as mock_cls:
            client = mock_cls.return_value.__enter__.return_value
            client.request.side_effect = [
                _redirect_response("https://hop.example.com/final"),
                _ok_response(b"final"),
            ]
            safe_sync_fetch("https://start.example.com/")

    assert [url.host for url in _requested_urls(client.request)] == [
        PUBLIC_IP,
        PUBLIC_IP_HOP,
    ]


# ---------------------------------------------------------------------------
# caller-supplied clients
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_request_with_validation_pins_the_validated_ip():
    resolver = _RebindingResolver({"sitemap.example.com": [[PUBLIC_IP], [PRIVATE_IP]]})
    recorded: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(200, content=b"<urlset/>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with patch("services.url_validation.socket.getaddrinfo", resolver):
            response, final_url = await async_request_with_validation(
                client,
                method="GET",
                url="https://sitemap.example.com/sitemap.xml",
            )

    assert response.status_code == 200
    assert final_url == "https://sitemap.example.com/sitemap.xml"
    assert recorded[0].url.host == PUBLIC_IP
    assert recorded[0].headers["host"] == "sitemap.example.com"
    assert recorded[0].extensions.get("sni_hostname") == "sitemap.example.com"


def test_sync_request_with_validation_pins_the_validated_ip():
    resolver = _RebindingResolver({"sync.example.com": [[PUBLIC_IP], [METADATA_IP]]})
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(200, content=b"ok")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with patch("services.url_validation.socket.getaddrinfo", resolver):
            response, _ = sync_request_with_validation(
                client,
                method="GET",
                url="https://sync.example.com/robots.txt",
            )

    assert response.status_code == 200
    assert recorded[0].url.host == PUBLIC_IP
    assert recorded[0].headers["host"] == "sync.example.com"
