"""Tests for audit submission deduplication service (AEX-21).

Covers key building, normalisation, check/set/clear helpers, and the
per-job cleanup utility.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.audit_dedup_service import (
    DEDUP_KEY_PREFIX,
    DEDUP_TTL_SECONDS,
    _normalise_url_for_dedup,
    build_dedup_key,
    check_dedup,
    clear_dedup,
    clear_dedup_for_job,
    set_dedup,
)


# ---------------------------------------------------------------------------
# URL normalisation
# ---------------------------------------------------------------------------


class TestNormaliseUrlForDedup:
    def test_strips_www_prefix(self):
        assert _normalise_url_for_dedup("https://www.example.com/page") == "example.com/page"

    def test_lowercases_host(self):
        assert _normalise_url_for_dedup("https://EXAMPLE.COM/Page") == "example.com/Page"

    def test_strips_trailing_slash(self):
        assert _normalise_url_for_dedup("https://example.com/") == "example.com/"

    def test_strips_default_port_443(self):
        result = _normalise_url_for_dedup("https://example.com:443/path")
        assert ":443" not in result
        assert result == "example.com/path"

    def test_strips_default_port_80(self):
        result = _normalise_url_for_dedup("http://example.com:80/path")
        assert ":80" not in result

    def test_keeps_non_default_port(self):
        result = _normalise_url_for_dedup("https://example.com:8080/path")
        assert ":8080" in result

    def test_preserves_query_string(self):
        result = _normalise_url_for_dedup("https://example.com/page?q=hello&lang=en")
        assert "?q=hello&lang=en" in result

    def test_ignores_fragment(self):
        result = _normalise_url_for_dedup("https://example.com/page#section")
        assert "#section" not in result

    def test_trailing_dot_on_host(self):
        result = _normalise_url_for_dedup("https://example.com./page")
        assert result == "example.com/page"

    def test_equivalent_urls_produce_same_key(self):
        a = _normalise_url_for_dedup("https://www.EXAMPLE.com:443/path")
        b = _normalise_url_for_dedup("https://example.com/path")
        assert a == b


# ---------------------------------------------------------------------------
# Key builder
# ---------------------------------------------------------------------------


class TestBuildDedupKey:
    def test_website_audit_key(self):
        key = build_dedup_key(
            user_id=42,
            target_url="https://www.example.com/page",
            target_name=None,
            tier="fast",
        )
        assert key.startswith(f"{DEDUP_KEY_PREFIX}:42:")
        assert key.endswith(":fast")
        assert ":" in key  # has hash segment

    def test_brand_audit_key(self):
        key = build_dedup_key(
            user_id=7,
            target_url=None,
            target_name="Acme Corp",
            tier="smart",
        )
        assert key.startswith(f"{DEDUP_KEY_PREFIX}:7:")
        assert key.endswith(":smart")

    def test_project_scoped_key_differs(self):
        base = build_dedup_key(
            user_id=1,
            target_url="https://example.com",
            target_name=None,
            tier="fast",
        )
        scoped = build_dedup_key(
            user_id=1,
            target_url="https://example.com",
            target_name=None,
            tier="fast",
            project_id=99,
        )
        assert scoped == base + ":99"
        assert base != scoped

    def test_different_tiers_produce_different_keys(self):
        k1 = build_dedup_key(user_id=1, target_url="https://a.com", target_name=None, tier="fast")
        k2 = build_dedup_key(user_id=1, target_url="https://a.com", target_name=None, tier="smart")
        assert k1 != k2

    def test_equivalent_urls_same_key(self):
        k1 = build_dedup_key(
            user_id=1, target_url="https://WWW.Example.com:443/", target_name=None, tier="fast"
        )
        k2 = build_dedup_key(
            user_id=1, target_url="https://example.com/", target_name=None, tier="fast"
        )
        assert k1 == k2

    def test_brand_name_case_insensitive(self):
        k1 = build_dedup_key(user_id=1, target_url=None, target_name="Acme Corp", tier="fast")
        k2 = build_dedup_key(user_id=1, target_url=None, target_name="acme corp", tier="fast")
        assert k1 == k2

    def test_fallback_when_no_url_or_name(self):
        key = build_dedup_key(user_id=1, target_url=None, target_name=None, tier="fast")
        assert "unknown" not in key or key.startswith(DEDUP_KEY_PREFIX)


# ---------------------------------------------------------------------------
# Async helpers (mock redis)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis():
    """Return an AsyncMock that behaves like an aioredis client."""
    rc = AsyncMock()
    rc.get = AsyncMock(return_value=None)
    rc.setex = AsyncMock()
    rc.delete = AsyncMock()
    return rc


class TestCheckDedup:
    @pytest.mark.asyncio
    async def test_returns_none_when_key_absent(self, mock_redis):
        mock_redis.get.return_value = None
        result = await check_dedup(mock_redis, "audit:dedup:test:key")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_job_id_when_key_set(self, mock_redis):
        mock_redis.get.return_value = b"job-abc-123"
        result = await check_dedup(mock_redis, "audit:dedup:test:key")
        assert result == "job-abc-123"

    @pytest.mark.asyncio
    async def test_handles_string_return(self, mock_redis):
        mock_redis.get.return_value = "job-xyz"
        result = await check_dedup(mock_redis, "audit:dedup:test:key")
        assert result == "job-xyz"


class TestSetDedup:
    @pytest.mark.asyncio
    async def test_calls_setex_with_correct_args(self, mock_redis):
        await set_dedup(mock_redis, "my:key", "job-1")
        mock_redis.setex.assert_awaited_once_with("my:key", DEDUP_TTL_SECONDS, "job-1")

    @pytest.mark.asyncio
    async def test_custom_ttl(self, mock_redis):
        await set_dedup(mock_redis, "my:key", "job-1", ttl=60)
        mock_redis.setex.assert_awaited_once_with("my:key", 60, "job-1")


class TestClearDedup:
    @pytest.mark.asyncio
    async def test_calls_delete(self, mock_redis):
        await clear_dedup(mock_redis, "my:key")
        mock_redis.delete.assert_awaited_once_with("my:key")

    @pytest.mark.asyncio
    async def test_suppresses_exceptions(self, mock_redis):
        mock_redis.delete.side_effect = ConnectionError("gone")
        # Should not raise
        await clear_dedup(mock_redis, "my:key")


class TestClearDedupForJob:
    @pytest.mark.asyncio
    async def test_derives_key_and_clears(self, mock_redis):
        job = MagicMock()
        job.user_id = 42
        job.url = "https://example.com/page"
        job.target_url = "https://example.com/page"
        job.target_name = None
        job.requested_tier = "fast"
        job.tier = "fast"
        job.project_id = None
        job.job_id = "job-xyz"

        await clear_dedup_for_job(mock_redis, job=job)
        mock_redis.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_brand_job(self, mock_redis):
        job = MagicMock()
        job.user_id = 5
        job.url = ""
        job.target_url = None
        job.target_name = "Acme Corp"
        job.requested_tier = "smart"
        job.tier = "smart"
        job.project_id = 10
        job.job_id = "job-brand"

        await clear_dedup_for_job(mock_redis, job=job)
        mock_redis.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_suppresses_errors(self, mock_redis):
        job = MagicMock()
        job.user_id = 1
        job.url = "https://example.com"
        job.target_url = "https://example.com"
        job.target_name = None
        job.requested_tier = None
        job.tier = "fast"
        job.project_id = None
        job.job_id = "j"
        mock_redis.delete.side_effect = Exception("boom")

        # Should not raise
        await clear_dedup_for_job(mock_redis, job=job)
