"""Tests for backend/core/redis_client.py — SEC-04."""

import asyncio
import os
from unittest.mock import patch, MagicMock, AsyncMock


from core.redis_client import (
    _resolve_redis_url,
    _is_tls_url,
    get_async_redis_client,
    get_async_redis,
    get_sync_redis_client,
    get_sync_redis,
    validate_redis_url_production,
)


# ---------------------------------------------------------------------------
# _resolve_redis_url
# ---------------------------------------------------------------------------


class TestResolveRedisUrl:
    def test_defaults_to_compose_url(self):
        with patch.dict(os.environ, {}, clear=True):
            # Ensure REDIS_URL is not in env
            os.environ.pop("REDIS_URL", None)
            assert _resolve_redis_url() == "redis://redis:6379"

    def test_reads_env_var(self):
        with patch.dict(os.environ, {"REDIS_URL": "redis://:secret@prod:6380"}):
            assert _resolve_redis_url() == "redis://:secret@prod:6380"


# ---------------------------------------------------------------------------
# _is_tls_url
# ---------------------------------------------------------------------------


class TestIsTlsUrl:
    def test_redis_scheme_not_tls(self):
        assert _is_tls_url("redis://host:6379") is False

    def test_rediss_scheme_is_tls(self):
        assert _is_tls_url("rediss://:pass@host:6380") is True

    def test_rediss_sentinel_is_tls(self):
        assert _is_tls_url("rediss+sentinel://:pass@host:26379") is True


# ---------------------------------------------------------------------------
# get_async_redis_client
# ---------------------------------------------------------------------------


class TestGetAsyncRedisClient:
    @patch("core.redis_client.async_redis_lib.from_url")
    def test_creates_client_with_defaults(self, mock_from_url):
        mock_from_url.return_value = MagicMock()
        get_async_redis_client(url="redis://test:6379")
        mock_from_url.assert_called_once_with(
            "redis://test:6379",
            decode_responses=True,
            socket_timeout=30.0,
            socket_connect_timeout=3.0,
            health_check_interval=30,
        )

    @patch("core.redis_client.async_redis_lib.from_url")
    def test_custom_timeouts(self, mock_from_url):
        mock_from_url.return_value = MagicMock()
        get_async_redis_client(
            url="redis://x:6379", socket_timeout=10.0, socket_connect_timeout=5.0
        )
        mock_from_url.assert_called_once_with(
            "redis://x:6379",
            decode_responses=True,
            socket_timeout=10.0,
            socket_connect_timeout=5.0,
            health_check_interval=30,
        )


# ---------------------------------------------------------------------------
# get_async_redis (context manager)
# ---------------------------------------------------------------------------


class TestGetAsyncRedisContextManager:
    @patch("core.redis_client.async_redis_lib.from_url")
    def test_context_manager_closes_client(self, mock_from_url):
        mock_client = AsyncMock()
        mock_from_url.return_value = mock_client

        async def _run():
            async with get_async_redis(url="redis://test:6379") as c:
                assert c is mock_client
            mock_client.aclose.assert_awaited_once()

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# get_sync_redis_client
# ---------------------------------------------------------------------------


class TestGetSyncRedisClient:
    @patch("core.redis_client.sync_redis_lib.from_url")
    def test_creates_sync_client(self, mock_from_url):
        mock_from_url.return_value = MagicMock()
        get_sync_redis_client(url="redis://test:6379")
        mock_from_url.assert_called_once_with(
            "redis://test:6379",
            decode_responses=True,
            socket_timeout=30.0,
            socket_connect_timeout=3.0,
        )


# ---------------------------------------------------------------------------
# get_sync_redis (context manager)
# ---------------------------------------------------------------------------


class TestGetSyncRedisContextManager:
    @patch("core.redis_client.sync_redis_lib.from_url")
    def test_context_manager_closes_client(self, mock_from_url):
        mock_client = MagicMock()
        mock_from_url.return_value = mock_client

        with get_sync_redis(url="redis://test:6379") as c:
            assert c is mock_client
        mock_client.close.assert_called_once()


# ---------------------------------------------------------------------------
# validate_redis_url_production
# ---------------------------------------------------------------------------


class TestValidateRedisUrlProduction:
    def test_authenticated_url_passes(self):
        issues = validate_redis_url_production("redis://:strongpassword@redis-prod:6379")
        assert issues == []

    def test_authenticated_tls_url_passes(self):
        issues = validate_redis_url_production("rediss://:strongpassword@redis-prod:6380")
        assert issues == []

    def test_no_password_is_flagged(self):
        issues = validate_redis_url_production("redis://external-redis:6379")
        assert len(issues) >= 1
        assert any("no password" in i.lower() for i in issues)

    def test_dev_default_without_password_is_flagged(self):
        issues = validate_redis_url_production("redis://redis:6379")
        assert len(issues) >= 1
        assert any("dev default" in i.lower() or "no password" in i.lower() for i in issues)

    def test_localhost_without_password_is_flagged(self):
        issues = validate_redis_url_production("redis://localhost:6379")
        assert len(issues) >= 1

    def test_empty_hostname(self):
        issues = validate_redis_url_production("redis://")
        assert any("no hostname" in i.lower() for i in issues)

    def test_user_with_password_passes(self):
        """redis://user:pass@host is valid."""
        issues = validate_redis_url_production("redis://default:secr3t@prod-redis:6379")
        assert issues == []
