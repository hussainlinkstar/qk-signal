"""Tests for smart crawl aggregation routing in SitemapCrawlerService."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers — lightweight fakes
# ---------------------------------------------------------------------------


def _utcnow():
    return datetime.now(timezone.utc)


def _make_crawl_job(
    job_id: str = "job-1",
    status: str = "running",
    total_urls: int = 3,
    completed_urls: int = 2,
    failed_urls: int = 0,
    credits_consumed: int = 0,
):
    job = MagicMock()
    job.id = job_id
    job.status = status
    job.total_urls = total_urls
    job.completed_urls = completed_urls
    job.failed_urls = failed_urls
    job.credits_consumed = credits_consumed
    job.error = None
    job.completed_at = None
    job.project_id = 1
    return job


def _make_audit(request_id, url, geo=70, seo=80, aeo=60, page_type="blog_article"):
    audit = MagicMock()
    audit.request_id = request_id
    audit.url = url
    audit.geo_score = geo
    audit.seo_score = seo
    audit.aeo_score = aeo
    audit.full_report = {"recommendations": []}
    return audit


def _make_audit_job(request_id, status="succeeded"):
    aj = MagicMock()
    aj.request_id = request_id
    aj.status = status
    aj.created_at = _utcnow()
    return aj


# ---------------------------------------------------------------------------
# Import under test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch):
    """Provide env vars so that importing the service doesn't fail."""
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-for-testing")
    monkeypatch.setenv("JWT_REFRESH_SECRET_KEY", "test-refresh-key")


# ---------------------------------------------------------------------------
# Tests — aggregate routing
# ---------------------------------------------------------------------------


class TestAggregateForJob:
    """_aggregate_for_job should route to smart vs standard aggregation."""

    @pytest.mark.asyncio
    async def test_routes_to_smart_when_metadata_present(self):
        """When Redis has smart_metadata, aggregate_smart_results is called."""
        from services.sitemap_crawler_service import SitemapCrawlerService

        svc = SitemapCrawlerService.__new__(SitemapCrawlerService)
        crawl_job = _make_crawl_job()

        smart_meta = {
            "mode": "smart_sample",
            "total_site_urls": 100,
            "sampled_urls": 5,
            "page_type_distribution": {"blog_article": 50, "product": 30, "homepage": 1},
        }

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(smart_meta))
        mock_redis.__aenter__ = AsyncMock(return_value=mock_redis)
        mock_redis.__aexit__ = AsyncMock(return_value=False)

        db = MagicMock()

        with patch("services.sitemap_crawler_service.get_async_redis", return_value=mock_redis):
            with patch.object(
                svc, "aggregate_smart_results", return_value={"smart": True}
            ) as mock_smart:
                with patch.object(
                    svc, "aggregate_results", return_value={"smart": False}
                ) as mock_standard:
                    result = await svc._aggregate_for_job(db=db, crawl_job=crawl_job)

        mock_smart.assert_called_once_with(db=db, job=crawl_job, smart_metadata=smart_meta)
        mock_standard.assert_not_called()
        assert result == {"smart": True}

    @pytest.mark.asyncio
    async def test_routes_to_standard_when_no_metadata(self):
        """When Redis has no smart_metadata, aggregate_results is called."""
        from services.sitemap_crawler_service import SitemapCrawlerService

        svc = SitemapCrawlerService.__new__(SitemapCrawlerService)
        crawl_job = _make_crawl_job()

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.__aenter__ = AsyncMock(return_value=mock_redis)
        mock_redis.__aexit__ = AsyncMock(return_value=False)

        db = MagicMock()

        with patch("services.sitemap_crawler_service.get_async_redis", return_value=mock_redis):
            with patch.object(svc, "aggregate_smart_results") as mock_smart:
                with patch.object(
                    svc, "aggregate_results", return_value={"standard": True}
                ) as mock_standard:
                    result = await svc._aggregate_for_job(db=db, crawl_job=crawl_job)

        mock_standard.assert_called_once_with(db=db, job=crawl_job)
        mock_smart.assert_not_called()
        assert result == {"standard": True}

    @pytest.mark.asyncio
    async def test_falls_back_to_standard_on_redis_error(self):
        """When Redis fails, falls back to standard aggregation."""
        from services.sitemap_crawler_service import SitemapCrawlerService

        svc = SitemapCrawlerService.__new__(SitemapCrawlerService)
        crawl_job = _make_crawl_job()

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=Exception("redis down"))
        mock_redis.__aenter__ = AsyncMock(return_value=mock_redis)
        mock_redis.__aexit__ = AsyncMock(return_value=False)

        db = MagicMock()

        with patch("services.sitemap_crawler_service.get_async_redis", return_value=mock_redis):
            with patch.object(
                svc, "aggregate_results", return_value={"fallback": True}
            ) as mock_std:
                result = await svc._aggregate_for_job(db=db, crawl_job=crawl_job)

        mock_std.assert_called_once()
        assert result == {"fallback": True}


class TestAggregateSmartResults:
    """aggregate_smart_results should add smart_crawl block with extrapolation."""

    def test_adds_smart_crawl_block(self):
        """Smart aggregation adds the smart_crawl key with extrapolation data."""
        from services.sitemap_crawler_service import SitemapCrawlerService

        svc = SitemapCrawlerService.__new__(SitemapCrawlerService)
        db = MagicMock()
        job = _make_crawl_job()

        base_results = {
            "aggregated_scores": {"geo": 70, "seo": 80, "aeo": 50, "site_health": 66.67},
            "score_distribution": {"80_plus": 0, "60_79": 1, "40_59": 1, "below_40": 0},
            "top_issues": [],
            "worst_pages": [],
            "best_pages": [],
            "page_type_breakdown": {
                "blog_article": {
                    "count": 2,
                    "avg_geo": 65,
                    "avg_seo": 75,
                    "avg_aeo": 45,
                    "avg_overall": 55,
                },
                "product": {
                    "count": 1,
                    "avg_geo": 80,
                    "avg_seo": 85,
                    "avg_aeo": 70,
                    "avg_overall": 78,
                },
            },
            "site_insights": [],
            "page_count": 3,
            "generated_at": "2024-01-01T00:00:00",
        }

        smart_metadata = {
            "mode": "smart_sample",
            "total_site_urls": 200,
            "sampled_urls": 3,
            "page_type_distribution": {"blog_article": 100, "product": 50, "homepage": 1},
        }

        with patch.object(svc, "aggregate_results", return_value=base_results):
            result = svc.aggregate_smart_results(db=db, job=job, smart_metadata=smart_metadata)

        assert "smart_crawl" in result
        sc = result["smart_crawl"]
        assert sc["mode"] == "smart_sample"
        assert sc["total_site_urls"] == 200
        assert sc["sampled_urls"] == 3
        assert sc["coverage_ratio"] == 0.015
        # blog_article avg_overall=55 < 60 → extrapolated
        assert len(sc["extrapolated_issues"]) == 1
        issue = sc["extrapolated_issues"][0]
        assert issue["page_type"] == "blog_article"
        assert issue["confidence"] == "high"  # 2 samples
        assert issue["estimated_total"] == 100

    def test_no_extrapolation_when_scores_ok(self):
        """No extrapolated issues when all page types score >= 60."""
        from services.sitemap_crawler_service import SitemapCrawlerService

        svc = SitemapCrawlerService.__new__(SitemapCrawlerService)
        db = MagicMock()
        job = _make_crawl_job()

        base_results = {
            "aggregated_scores": {"geo": 80, "seo": 85, "aeo": 75, "site_health": 80},
            "score_distribution": {"80_plus": 2, "60_79": 1, "40_59": 0, "below_40": 0},
            "top_issues": [],
            "worst_pages": [],
            "best_pages": [],
            "page_type_breakdown": {
                "blog_article": {
                    "count": 2,
                    "avg_geo": 80,
                    "avg_seo": 85,
                    "avg_aeo": 75,
                    "avg_overall": 80,
                },
            },
            "site_insights": [],
            "page_count": 2,
            "generated_at": "2024-01-01T00:00:00",
        }

        smart_metadata = {
            "mode": "smart_sample",
            "total_site_urls": 50,
            "sampled_urls": 2,
            "page_type_distribution": {"blog_article": 50},
        }

        with patch.object(svc, "aggregate_results", return_value=base_results):
            result = svc.aggregate_smart_results(db=db, job=job, smart_metadata=smart_metadata)

        assert result["smart_crawl"]["extrapolated_issues"] == []

    def test_returns_base_when_no_metadata(self):
        """When smart_metadata is None, returns base results unchanged."""
        from services.sitemap_crawler_service import SitemapCrawlerService

        svc = SitemapCrawlerService.__new__(SitemapCrawlerService)
        db = MagicMock()
        job = _make_crawl_job()

        base = {"test": True}
        with patch.object(svc, "aggregate_results", return_value=base):
            result = svc.aggregate_smart_results(db=db, job=job, smart_metadata=None)

        assert result == {"test": True}
        assert "smart_crawl" not in result

    def test_medium_confidence_with_single_sample(self):
        """Single-sample page types get 'medium' confidence."""
        from services.sitemap_crawler_service import SitemapCrawlerService

        svc = SitemapCrawlerService.__new__(SitemapCrawlerService)
        db = MagicMock()
        job = _make_crawl_job()

        base_results = {
            "aggregated_scores": {"geo": 40, "seo": 35, "aeo": 30, "site_health": 35},
            "score_distribution": {"80_plus": 0, "60_79": 0, "40_59": 0, "below_40": 1},
            "top_issues": [],
            "worst_pages": [],
            "best_pages": [],
            "page_type_breakdown": {
                "product": {
                    "count": 1,
                    "avg_geo": 40,
                    "avg_seo": 35,
                    "avg_aeo": 30,
                    "avg_overall": 35,
                },
            },
            "site_insights": [],
            "page_count": 1,
            "generated_at": "2024-01-01T00:00:00",
        }

        smart_metadata = {
            "mode": "smart_sample",
            "total_site_urls": 100,
            "sampled_urls": 1,
            "page_type_distribution": {"product": 80},
        }

        with patch.object(svc, "aggregate_results", return_value=base_results):
            result = svc.aggregate_smart_results(db=db, job=job, smart_metadata=smart_metadata)

        issues = result["smart_crawl"]["extrapolated_issues"]
        assert len(issues) == 1
        assert issues[0]["confidence"] == "medium"
