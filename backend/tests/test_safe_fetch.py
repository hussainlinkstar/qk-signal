"""Tests for the unified safe-fetch wrappers in url_validation.py.

Covers: SSRF blocking, redirect-hop validation, response size limits,
user-agent injection, and sync/async parity.
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

import httpx
import pytest

from services.url_validation import (
    ResponseTooLargeError,
    SSRFBlockedError,
    safe_async_fetch,
    safe_sync_fetch,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok_response(content: bytes = b"ok", status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, content=content)


def _redirect_response(location: str, status_code: int = 302) -> httpx.Response:
    return httpx.Response(status_code, headers={"location": location})


# ---------------------------------------------------------------------------
# safe_async_fetch
# ---------------------------------------------------------------------------


class TestSafeAsyncFetch:
    @pytest.mark.asyncio
    async def test_blocks_private_ip(self):
        with pytest.raises(SSRFBlockedError, match="Private or reserved"):
            await safe_async_fetch("http://192.168.1.1/admin")

    @pytest.mark.asyncio
    async def test_blocks_localhost(self):
        with pytest.raises(SSRFBlockedError, match="Localhost"):
            await safe_async_fetch("http://localhost:8000/secret")

    @pytest.mark.asyncio
    async def test_blocks_loopback(self):
        with pytest.raises(SSRFBlockedError, match="Private or reserved"):
            await safe_async_fetch("http://127.0.0.1/admin")

    @pytest.mark.asyncio
    async def test_blocks_link_local(self):
        with pytest.raises(SSRFBlockedError, match="Private or reserved"):
            await safe_async_fetch("http://169.254.169.254/metadata")

    @pytest.mark.asyncio
    async def test_blocks_non_http_scheme(self):
        with pytest.raises(SSRFBlockedError, match="http:// or https://"):
            await safe_async_fetch("ftp://example.com/file")

    @pytest.mark.asyncio
    async def test_allows_public_url(self):
        with patch("services.url_validation.httpx.AsyncClient") as mock_cls:
            mock_client = mock_cls.return_value.__aenter__.return_value
            mock_client.request.return_value = _ok_response(b"hello")
            response = await safe_async_fetch("https://example.com/page")
        assert response.status_code == 200
        assert response.content == b"hello"

    @pytest.mark.asyncio
    async def test_injects_user_agent(self):
        with patch("services.url_validation.httpx.AsyncClient") as mock_cls:
            mock_client = mock_cls.return_value.__aenter__.return_value
            mock_client.request.return_value = _ok_response()
            await safe_async_fetch("https://example.com")
        call_kwargs = mock_client.request.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers.get("User-Agent") == "Qiko Signal/1.0"

    @pytest.mark.asyncio
    async def test_custom_user_agent(self):
        with patch("services.url_validation.httpx.AsyncClient") as mock_cls:
            mock_client = mock_cls.return_value.__aenter__.return_value
            mock_client.request.return_value = _ok_response()
            await safe_async_fetch("https://example.com", user_agent="MyBot/2.0")
        call_kwargs = mock_client.request.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers.get("User-Agent") == "MyBot/2.0"

    @pytest.mark.asyncio
    async def test_respects_existing_user_agent_header(self):
        with patch("services.url_validation.httpx.AsyncClient") as mock_cls:
            mock_client = mock_cls.return_value.__aenter__.return_value
            mock_client.request.return_value = _ok_response()
            await safe_async_fetch(
                "https://example.com",
                headers={"User-Agent": "CustomBot/1.0"},
            )
        call_kwargs = mock_client.request.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers.get("User-Agent") == "CustomBot/1.0"

    @pytest.mark.asyncio
    async def test_response_too_large(self):
        big_body = b"x" * 1001
        with patch("services.url_validation.httpx.AsyncClient") as mock_cls:
            mock_client = mock_cls.return_value.__aenter__.return_value
            mock_client.request.return_value = _ok_response(big_body)
            with pytest.raises(ResponseTooLargeError, match="1,001 bytes"):
                await safe_async_fetch(
                    "https://example.com",
                    max_response_bytes=1000,
                )

    @pytest.mark.asyncio
    async def test_response_size_limit_zero_disables_check(self):
        big_body = b"x" * 50_000_000
        with patch("services.url_validation.httpx.AsyncClient") as mock_cls:
            mock_client = mock_cls.return_value.__aenter__.return_value
            mock_client.request.return_value = _ok_response(big_body)
            response = await safe_async_fetch(
                "https://example.com",
                max_response_bytes=0,
            )
        assert len(response.content) == 50_000_000

    @pytest.mark.asyncio
    async def test_redirect_to_private_ip_blocked(self):
        with patch("services.url_validation.httpx.AsyncClient") as mock_cls:
            mock_client = mock_cls.return_value.__aenter__.return_value
            mock_client.request.return_value = _redirect_response("http://192.168.1.1/admin")
            with pytest.raises(SSRFBlockedError, match="Redirect to forbidden"):
                await safe_async_fetch("https://example.com")

    @pytest.mark.asyncio
    async def test_redirect_to_localhost_blocked(self):
        with patch("services.url_validation.httpx.AsyncClient") as mock_cls:
            mock_client = mock_cls.return_value.__aenter__.return_value
            mock_client.request.return_value = _redirect_response("http://localhost:8000/secret")
            with pytest.raises(SSRFBlockedError, match="Redirect to forbidden"):
                await safe_async_fetch("https://example.com")

    @pytest.mark.asyncio
    async def test_redirect_to_safe_url_followed(self):
        responses = [
            _redirect_response("https://www.example.com/page"),
            _ok_response(b"final"),
        ]
        with patch("services.url_validation.httpx.AsyncClient") as mock_cls:
            mock_client = mock_cls.return_value.__aenter__.return_value
            mock_client.request.side_effect = responses
            response = await safe_async_fetch("https://example.com")
        assert response.status_code == 200
        assert response.content == b"final"

    @pytest.mark.asyncio
    async def test_too_many_redirects(self):
        with patch("services.url_validation.httpx.AsyncClient") as mock_cls:
            mock_client = mock_cls.return_value.__aenter__.return_value
            mock_client.request.return_value = _redirect_response("https://example.com/loop")
            with pytest.raises(ValueError, match="Too many redirects"):
                await safe_async_fetch("https://example.com")

    @pytest.mark.asyncio
    async def test_passes_json_body(self):
        with patch("services.url_validation.httpx.AsyncClient") as mock_cls:
            mock_client = mock_cls.return_value.__aenter__.return_value
            mock_client.request.return_value = _ok_response()
            await safe_async_fetch(
                "https://example.com/webhook",
                method="POST",
                json={"key": "value"},
            )
        call_kwargs = mock_client.request.call_args
        assert call_kwargs.kwargs.get("json") == {"key": "value"}

    @pytest.mark.asyncio
    async def test_passes_params(self):
        with patch("services.url_validation.httpx.AsyncClient") as mock_cls:
            mock_client = mock_cls.return_value.__aenter__.return_value
            mock_client.request.return_value = _ok_response()
            await safe_async_fetch(
                "https://example.com/api",
                params={"q": "test"},
            )
        call_kwargs = mock_client.request.call_args
        assert call_kwargs.kwargs.get("params") == {"q": "test"}

    @pytest.mark.asyncio
    async def test_body_not_resent_on_redirect(self):
        responses = [
            _redirect_response("https://example.com/other"),
            _ok_response(b"done"),
        ]
        with patch("services.url_validation.httpx.AsyncClient") as mock_cls:
            mock_client = mock_cls.return_value.__aenter__.return_value
            mock_client.request.side_effect = responses
            await safe_async_fetch(
                "https://example.com",
                method="POST",
                json={"data": 1},
            )
        first_call = mock_client.request.call_args_list[0]
        second_call = mock_client.request.call_args_list[1]
        assert first_call.kwargs.get("json") == {"data": 1}
        assert "json" not in second_call.kwargs

    @pytest.mark.asyncio
    async def test_http2_flag_passed_to_client(self):
        with patch("services.url_validation.httpx.AsyncClient") as mock_cls:
            mock_client = mock_cls.return_value.__aenter__.return_value
            mock_client.request.return_value = _ok_response()
            await safe_async_fetch("https://example.com", http2=True)
        init_kwargs = mock_cls.call_args
        assert init_kwargs.kwargs.get("http2") is True

    @pytest.mark.asyncio
    async def test_blocks_dns_rebinding(self):
        """Hostnames that resolve to private IPs are blocked."""
        import socket

        def fake_getaddrinfo(host, port, type):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)),
            ]

        with patch("services.url_validation.socket.getaddrinfo", fake_getaddrinfo):
            with pytest.raises(SSRFBlockedError, match="Private or reserved"):
                await safe_async_fetch("https://evil-rebinding.example.com")


# ---------------------------------------------------------------------------
# safe_sync_fetch
# ---------------------------------------------------------------------------


class TestSafeSyncFetch:
    def test_blocks_private_ip(self):
        with pytest.raises(SSRFBlockedError, match="Private or reserved"):
            safe_sync_fetch("http://10.0.0.5/admin")

    def test_blocks_localhost(self):
        with pytest.raises(SSRFBlockedError, match="Localhost"):
            safe_sync_fetch("http://localhost:3000")

    def test_allows_public_url(self):
        with patch("services.url_validation.httpx.Client") as mock_cls:
            mock_client = mock_cls.return_value.__enter__.return_value
            mock_client.request.return_value = _ok_response(b"sync ok")
            response = safe_sync_fetch("https://example.com")
        assert response.content == b"sync ok"

    def test_response_too_large(self):
        big_body = b"x" * 2001
        with patch("services.url_validation.httpx.Client") as mock_cls:
            mock_client = mock_cls.return_value.__enter__.return_value
            mock_client.request.return_value = _ok_response(big_body)
            with pytest.raises(ResponseTooLargeError):
                safe_sync_fetch("https://example.com", max_response_bytes=2000)

    def test_redirect_to_private_ip_blocked(self):
        with patch("services.url_validation.httpx.Client") as mock_cls:
            mock_client = mock_cls.return_value.__enter__.return_value
            mock_client.request.return_value = _redirect_response(
                "http://169.254.169.254/latest/meta-data"
            )
            with pytest.raises(SSRFBlockedError, match="Redirect to forbidden"):
                safe_sync_fetch("https://example.com")

    def test_redirect_followed_safely(self):
        responses = [
            _redirect_response("https://www.example.com"),
            _ok_response(b"redirected"),
        ]
        with patch("services.url_validation.httpx.Client") as mock_cls:
            mock_client = mock_cls.return_value.__enter__.return_value
            mock_client.request.side_effect = responses
            response = safe_sync_fetch("https://example.com")
        assert response.content == b"redirected"

    def test_injects_user_agent(self):
        with patch("services.url_validation.httpx.Client") as mock_cls:
            mock_client = mock_cls.return_value.__enter__.return_value
            mock_client.request.return_value = _ok_response()
            safe_sync_fetch("https://example.com")
        call_kwargs = mock_client.request.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers.get("User-Agent") == "Qiko Signal/1.0"

    def test_passes_json_and_method(self):
        with patch("services.url_validation.httpx.Client") as mock_cls:
            mock_client = mock_cls.return_value.__enter__.return_value
            mock_client.request.return_value = _ok_response()
            safe_sync_fetch(
                "https://example.com/hook",
                method="POST",
                json={"event": "test"},
            )
        call_args = mock_client.request.call_args
        assert call_args[0][0] == "POST"
        assert call_args.kwargs.get("json") == {"event": "test"}

    def test_too_many_redirects(self):
        with patch("services.url_validation.httpx.Client") as mock_cls:
            mock_client = mock_cls.return_value.__enter__.return_value
            mock_client.request.return_value = _redirect_response("https://example.com/bounce")
            with pytest.raises(ValueError, match="Too many redirects"):
                safe_sync_fetch("https://example.com")

    def test_blocks_dns_rebinding(self):
        import socket

        def fake_getaddrinfo(host, port, type):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.16.0.1", 443)),
            ]

        with patch("services.url_validation.socket.getaddrinfo", fake_getaddrinfo):
            with pytest.raises(SSRFBlockedError, match="Private or reserved"):
                safe_sync_fetch("https://looks-public.example.com")
