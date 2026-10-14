from __future__ import annotations

import gzip
import io
import json
import os
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree
from defusedxml.ElementTree import fromstring as defused_fromstring

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

import models
from auth.credits import calculate_audit_credit_cost
from core.redis_client import get_async_redis
from job_models import JOB_STATUS_QUEUED, AuditJobPayload
from services.email_service import EmailService
from services.project_audit_scope import declare_audit_project_scope
from services.reports.audit_result_adapter import extract_normalized_recommendation_items
from services.url_validation import async_request_with_validation, normalize_and_validate_url

from services.queue_routing import resolve_queue_for_tier, LEGACY_QUEUE_NAME as AUDIT_QUEUE_NAME

DEFAULT_PROVIDER = (
    os.getenv("EXTERNAL_API_DEFAULT_PROVIDER") or "google"
).strip().lower() or "google"
DEFAULT_TIER = "fast"
SITEMAP_MAX_RESPONSE_BYTES = int(os.getenv("SITEMAP_MAX_RESPONSE_BYTES", str(5 * 1024 * 1024)))
SITEMAP_MAX_DECOMPRESSED_BYTES = int(
    os.getenv("SITEMAP_MAX_DECOMPRESSED_BYTES", str(10 * 1024 * 1024))
)


def _extract_page_type(audit: Any) -> str:
    """Extract page_type from an audit's full_report metadata, falling back to URL detection."""
    report = audit.full_report if isinstance(getattr(audit, "full_report", None), dict) else {}
    metadata = report.get("metadata") if isinstance(report.get("metadata"), dict) else {}
    page_type = str(metadata.get("page_type") or "").strip()
    if page_type:
        return page_type
    # Fallback: detect from URL
    url = str(getattr(audit, "url", "") or "").strip()
    if url:
        try:
            from services.page_type_detector import detect_page_type

            return detect_page_type(url=url)
        except ImportError:
            pass
    return "generic"


def _build_site_insights(
    *,
    page_rows: list[dict[str, Any]],
    recommendation_counter: Counter,
    page_type_summary: dict[str, Any],
) -> list[str]:
    """Generate human-readable site-wide insights from aggregated audit data."""
    insights: list[str] = []
    if not page_rows:
        return insights

    # Identify weakest page types
    for ptype, data in sorted(
        page_type_summary.items(),
        key=lambda x: x[1].get("avg_overall") or 0,
    ):
        avg = data.get("avg_overall")
        count = data.get("count", 0)
        if avg is not None and avg < 40 and count > 0:
            try:
                from services.page_type_detector import get_page_type_label

                label = get_page_type_label(ptype)
            except ImportError:
                label = ptype
            insights.append(
                f"{label} pages (n={count}) have a critically low average score of {avg:.1f}/100 "
                f"and should be prioritized for improvement."
            )

    # Schema coverage insight
    schema_issues = recommendation_counter.get("schema", 0) + recommendation_counter.get(
        "structured_data", 0
    )
    if schema_issues > len(page_rows) * 0.5:
        insights.append(
            f"Schema/structured data issues were found on {schema_issues} of {len(page_rows)} pages. "
            "A site-wide schema implementation strategy is recommended."
        )

    # Score variance insight
    overall_values = [
        float(r["overall"]) for r in page_rows if isinstance(r.get("overall"), (int, float))
    ]
    if len(overall_values) >= 3:
        score_range = max(overall_values) - min(overall_values)
        if score_range > 40:
            insights.append(
                f"Score variance is very high ({score_range:.0f} points between best and worst pages). "
                "Consider standardizing content quality and technical implementation across the site."
            )

    return insights


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1].lower()
    return tag.lower()


def _normalize_page_url(value: str) -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    try:
        return normalize_and_validate_url(candidate)
    except ValueError:
        return None


def _decompress_gzip_with_limit(body: bytes) -> bytes:
    with gzip.GzipFile(fileobj=io.BytesIO(body), mode="rb") as gzip_stream:
        decompressed = gzip_stream.read(SITEMAP_MAX_DECOMPRESSED_BYTES + 1)
    if len(decompressed) > SITEMAP_MAX_DECOMPRESSED_BYTES:
        raise ValueError("Sitemap gzip payload is too large after decompression.")
    return decompressed


class SitemapCrawlerService:
    def __init__(
        self,
        *,
        queue_name: str = AUDIT_QUEUE_NAME,
        provider: str = DEFAULT_PROVIDER,
        tier: str = DEFAULT_TIER,
        max_concurrency: int = 10,
    ) -> None:
        self.queue_name = queue_name
        self.provider = provider
        self.tier = tier
        self.max_concurrency = max(1, int(max_concurrency))

    @staticmethod
    def pending_urls_key(crawl_job_id: str) -> str:
        return f"sitemap:crawl:{crawl_job_id}:pending_urls"

    @staticmethod
    def inflight_key(crawl_job_id: str) -> str:
        return f"sitemap:crawl:{crawl_job_id}:inflight"

    @staticmethod
    def site_context_key(crawl_job_id: str) -> str:
        return f"sitemap:crawl:{crawl_job_id}:site_context"

    async def parse_sitemap(self, sitemap_url: str, max_urls: int = 500) -> list[str]:
        normalized_url = _normalize_page_url(sitemap_url)
        if normalized_url is None:
            raise ValueError("Sitemap URL must be a valid http(s) URL.")

        collected: list[str] = []
        seen_sitemaps: set[str] = set()
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            await self._collect_sitemap_urls(
                client=client,
                sitemap_url=normalized_url,
                collected=collected,
                seen_sitemaps=seen_sitemaps,
                max_urls=max(1, int(max_urls)),
            )

        deduped: list[str] = []
        seen_pages: set[str] = set()
        for url in collected:
            normalized_page = _normalize_page_url(url)
            if normalized_page and normalized_page not in seen_pages:
                seen_pages.add(normalized_page)
                deduped.append(normalized_page)
            if len(deduped) >= max_urls:
                break
        return deduped

    async def _collect_sitemap_urls(
        self,
        *,
        client: httpx.AsyncClient,
        sitemap_url: str,
        collected: list[str],
        seen_sitemaps: set[str],
        max_urls: int,
    ) -> None:
        normalized_sitemap = _normalize_page_url(sitemap_url)
        if normalized_sitemap is None or normalized_sitemap in seen_sitemaps:
            return
        if len(collected) >= max_urls:
            return

        seen_sitemaps.add(normalized_sitemap)
        response, _ = await async_request_with_validation(
            client,
            method="GET",
            url=normalized_sitemap,
        )
        response.raise_for_status()

        body = response.content
        if len(body) > SITEMAP_MAX_RESPONSE_BYTES:
            raise ValueError("Sitemap response is too large.")
        content_type = (response.headers.get("content-type") or "").lower()
        if normalized_sitemap.endswith(".gz") or "gzip" in content_type:
            body = _decompress_gzip_with_limit(body)

        try:
            root = defused_fromstring(body)
        except ElementTree.ParseError as exc:
            raise ValueError(f"Sitemap is not valid XML: {normalized_sitemap}") from exc

        root_name = _local_name(root.tag)
        if root_name == "sitemapindex":
            for sitemap_node in root:
                if _local_name(sitemap_node.tag) != "sitemap":
                    continue
                for loc_node in sitemap_node:
                    if _local_name(loc_node.tag) != "loc":
                        continue
                    nested_url = _normalize_page_url(loc_node.text or "")
                    if nested_url is None:
                        continue
                    await self._collect_sitemap_urls(
                        client=client,
                        sitemap_url=nested_url,
                        collected=collected,
                        seen_sitemaps=seen_sitemaps,
                        max_urls=max_urls,
                    )
                    if len(collected) >= max_urls:
                        return
            return

        if root_name == "urlset":
            for url_node in root:
                if _local_name(url_node.tag) != "url":
                    continue
                for loc_node in url_node:
                    if _local_name(loc_node.tag) != "loc":
                        continue
                    page_url = _normalize_page_url(loc_node.text or "")
                    if page_url is None:
                        continue
                    collected.append(page_url)
                    if len(collected) >= max_urls:
                        return
            return

        # Fallback for non-standard sitemap wrappers.
        for loc_node in root.iter():
            if _local_name(loc_node.tag) != "loc":
                continue
            candidate = _normalize_page_url(loc_node.text or "")
            if candidate is None:
                continue
            collected.append(candidate)
            if len(collected) >= max_urls:
                return

    def estimate_crawl(self, *, url_count: int) -> dict[str, int]:
        normalized_count = max(0, int(url_count))
        per_url_credit_cost = calculate_audit_credit_cost(
            provider=self.provider,
            tier=self.tier,
            entities_count=0,
        )
        return {
            "url_count": normalized_count,
            "per_url_credit_cost": per_url_credit_cost,
            "estimated_credit_cost": normalized_count * per_url_credit_cost,
        }

    async def estimate_crawl_from_sitemap(
        self, *, sitemap_url: str, max_urls: int = 500
    ) -> dict[str, int]:
        urls = await self.parse_sitemap(sitemap_url, max_urls=max_urls)
        return self.estimate_crawl(url_count=len(urls))

    async def start_crawl(
        self,
        *,
        db: Session,
        user: models.User,
        project: models.Project,
        sitemap_url: str,
        max_urls: int = 500,
    ) -> models.SitemapCrawlJob:
        crawl_job = models.SitemapCrawlJob(
            id=str(uuid4()),
            project_id=project.id,
            user_id=user.id,
            sitemap_url=sitemap_url,
            status="parsing",
            completed_urls=0,
            failed_urls=0,
            credits_consumed=0,
            schema_version="1",
        )
        db.add(crawl_job)
        db.commit()
        db.refresh(crawl_job)

        try:
            urls = await self.parse_sitemap(sitemap_url=sitemap_url, max_urls=max_urls)
        except Exception as exc:
            crawl_job.status = "failed"
            crawl_job.error = str(exc)
            crawl_job.completed_at = _utcnow()
            db.add(crawl_job)
            db.commit()
            db.refresh(crawl_job)
            raise

        if not urls:
            crawl_job.status = "failed"
            crawl_job.error = "No crawlable page URLs were found in this sitemap."
            crawl_job.completed_at = _utcnow()
            db.add(crawl_job)
            db.commit()
            db.refresh(crawl_job)
            raise HTTPException(status_code=400, detail=crawl_job.error)

        # SIGV2-1024: credits are internal soft limits; the crawl's scan
        # consumption is enforced per dispatched URL by the scan allowance.
        crawl_job.total_urls = len(urls)
        crawl_job.status = "queuing"
        crawl_job.error = None
        db.add(crawl_job)
        db.commit()

        async with get_async_redis() as redis_client:
            pending_key = self.pending_urls_key(crawl_job.id)
            inflight_key = self.inflight_key(crawl_job.id)
            site_ctx_key = self.site_context_key(crawl_job.id)
            pipeline = redis_client.pipeline()
            pipeline.delete(pending_key)
            pipeline.delete(inflight_key)
            pipeline.rpush(pending_key, *urls)
            pipeline.set(inflight_key, 0, ex=86400)
            pipeline.expire(pending_key, 86400)
            await pipeline.execute()

            # Build and store site structure context for page-type-aware audits
            try:
                from services.page_type_detector import (
                    build_site_structure_summary,
                    detect_page_type,
                )

                site_pages = [{"url": u, "page_type": detect_page_type(url=u)} for u in urls]
                site_summary = build_site_structure_summary(site_pages)
                if site_summary:
                    await redis_client.set(site_ctx_key, site_summary, ex=86400)
            except Exception:
                pass  # non-fatal: site context is a quality enhancement, not required

        await self.queue_next_batch(db=db, crawl_job=crawl_job, max_dispatch=self.max_concurrency)
        db.refresh(crawl_job)
        return crawl_job

    async def queue_next_batch(
        self,
        *,
        db: Session,
        crawl_job: models.SitemapCrawlJob,
        max_dispatch: int | None = None,
    ) -> int:
        if crawl_job.status in {"completed", "failed"}:
            return 0

        user = db.query(models.User).filter(models.User.id == crawl_job.user_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found for sitemap crawl.")

        async with get_async_redis() as redis_client:
            pending_key = self.pending_urls_key(crawl_job.id)
            inflight_key = self.inflight_key(crawl_job.id)

            inflight = int(await redis_client.get(inflight_key) or 0)
            available_slots = max(0, self.max_concurrency - inflight)
            if max_dispatch is not None:
                available_slots = min(available_slots, max(0, int(max_dispatch)))
            if available_slots <= 0:
                return 0

            # Fetch pre-built site structure context (may be None)
            site_ctx_key = self.site_context_key(crawl_job.id)
            _raw_site_ctx = await redis_client.get(site_ctx_key)
            site_structure_text = (
                _raw_site_ctx.decode("utf-8", errors="replace")
                if isinstance(_raw_site_ctx, bytes)
                else str(_raw_site_ctx)
                if _raw_site_ctx
                else None
            )

            per_url_credit_cost = calculate_audit_credit_cost(
                provider=self.provider,
                tier=self.tier,
                entities_count=0,
            )
            payloads: list[AuditJobPayload] = []

            from services.scan_allowance_service import consume_scan_allowance

            for _ in range(available_slots):
                next_url = await redis_client.lpop(pending_key)
                if not next_url:
                    break

                # Each crawled URL consumes one scan, matching the previous
                # per-URL internal credit charge (SIGV2-1024). When the
                # allowance is exhausted, dispatch stops and remaining URLs
                # stay queued for the next window.
                try:
                    consume_scan_allowance(db, user)
                except HTTPException as exc:
                    if exc.status_code == 402:
                        await redis_client.lpush(pending_key, next_url)
                        break
                    raise

                job_id = str(uuid4())
                request_id = f"sitemap-crawl:{crawl_job.id}:{job_id}"
                audit_job = models.AuditJob(
                    id=job_id,
                    user_id=user.id,
                    project_id=crawl_job.project_id,
                    sitemap_crawl_job_id=crawl_job.id,
                    status=JOB_STATUS_QUEUED,
                    source="sitemap_crawl",
                    audit_target_type=models.AuditTargetType.WEBSITE,
                    target_name=str(next_url),
                    target_url=str(next_url),
                    target_metadata={},
                    url=str(next_url),
                    provider=self.provider,
                    tier=self.tier,
                    estimated_credit_cost=per_url_credit_cost,
                    request_id=request_id,
                    # SIGV2-1129: a crawl child measures the customer's own
                    # site and consumes one of their scans, as before. The
                    # declaration is what keeps the loop above bounded, since
                    # the allowance count only sees declared customer scans.
                    scan_origin=models.SCAN_ORIGIN_CUSTOMER,
                )
                db.add(audit_job)

                payloads.append(
                    AuditJobPayload(
                        job_id=job_id,
                        request_id=request_id,
                        user_id=user.id,
                        url=str(next_url),
                        audit_target_type="website",
                        target_name=str(next_url),
                        target_url=str(next_url),
                        target_metadata={},
                        provider=self.provider,
                        tier=self.tier,
                        project_id=crawl_job.project_id,
                        estimated_credit_cost=per_url_credit_cost,
                        category="sitemap crawl",
                        charge_credits=True,
                        sitemap_crawl_job_id=crawl_job.id,
                        site_structure_summary=site_structure_text,
                        # SIGV2-1121: a crawled page belongs to the project's own
                        # site, and this write path says so explicitly.
                        project_scope=declare_audit_project_scope(category="sitemap crawl"),
                    )
                )
                await redis_client.incr(inflight_key)

            if not payloads:
                return 0

            db.commit()
            if crawl_job.status == "queuing":
                crawl_job.status = "running"
                db.add(crawl_job)
                db.commit()

            for payload in payloads:
                await redis_client.hset(
                    f"audit:job:{payload.job_id}",
                    mapping={
                        "status": JOB_STATUS_QUEUED,
                        "created_at": _utcnow().isoformat(),
                        "url": payload.url,
                        "project_id": str(crawl_job.project_id),
                        "request_id": payload.request_id,
                        "source": "sitemap_crawl",
                        "sitemap_crawl_job_id": crawl_job.id,
                        "estimated_credit_cost": str(per_url_credit_cost),
                    },
                )
                await redis_client.rpush(
                    resolve_queue_for_tier(payload.tier), json.dumps(payload.to_dict())
                )
                from services.job_ttl_dlq_service import set_ttl_queued

                await set_ttl_queued(redis_client, payload.job_id)

            return len(payloads)

    async def record_page_outcome(
        self,
        *,
        db: Session,
        crawl_job_id: str,
        success: bool,
        consumed_credit_cost: int = 0,
        error_message: str | None = None,
    ) -> None:
        crawl_job = (
            db.query(models.SitemapCrawlJob)
            .filter(models.SitemapCrawlJob.id == crawl_job_id)
            .first()
        )
        if crawl_job is None:
            return
        if crawl_job.status in {"completed", "failed"}:
            return

        if success:
            crawl_job.completed_urls = int(crawl_job.completed_urls or 0) + 1
            crawl_job.credits_consumed = int(crawl_job.credits_consumed or 0) + max(
                0, int(consumed_credit_cost)
            )
        else:
            crawl_job.failed_urls = int(crawl_job.failed_urls or 0) + 1
            if error_message:
                crawl_job.error = str(error_message)

        if crawl_job.status == "queuing":
            crawl_job.status = "running"

        db.add(crawl_job)
        db.commit()

        async with get_async_redis() as redis_client:
            pending_key = self.pending_urls_key(crawl_job.id)
            inflight_key = self.inflight_key(crawl_job.id)
            inflight_after = int(await redis_client.decr(inflight_key))
            if inflight_after < 0:
                await redis_client.set(inflight_key, 0, ex=86400)
                inflight_after = 0
            pending_count = int(await redis_client.llen(pending_key))

        total_urls = int(crawl_job.total_urls or 0)
        done_urls = int(crawl_job.completed_urls or 0) + int(crawl_job.failed_urls or 0)

        if total_urls > 0 and done_urls >= total_urls:
            if int(crawl_job.completed_urls or 0) > 0:
                crawl_job.aggregated_scores_json = await self._aggregate_for_job(
                    db=db, crawl_job=crawl_job
                )
                crawl_job.status = "completed"
            else:
                crawl_job.status = "failed"
                crawl_job.error = crawl_job.error or "All sitemap page audits failed."
            crawl_job.completed_at = _utcnow()
            db.add(crawl_job)
            db.commit()

            await self._cleanup_redis(crawl_job.id)
            if crawl_job.status == "completed":
                await self._queue_completion_email(db=db, crawl_job=crawl_job)
            return

        if pending_count > 0:
            await self.queue_next_batch(db=db, crawl_job=crawl_job, max_dispatch=1)
        elif inflight_after <= 0 and total_urls > 0 and done_urls >= total_urls:
            crawl_job.aggregated_scores_json = await self._aggregate_for_job(
                db=db, crawl_job=crawl_job
            )
            crawl_job.status = "completed"
            crawl_job.completed_at = _utcnow()
            db.add(crawl_job)
            db.commit()
            await self._cleanup_redis(crawl_job.id)
            await self._queue_completion_email(db=db, crawl_job=crawl_job)

    async def _aggregate_for_job(
        self,
        *,
        db: Session,
        crawl_job: models.SitemapCrawlJob,
    ) -> dict[str, Any]:
        """Route to smart or standard aggregation based on Redis metadata."""
        smart_meta_key = f"sitemap:crawl:{crawl_job.id}:smart_metadata"
        smart_metadata: dict[str, Any] | None = None
        try:
            async with get_async_redis() as redis_client:
                raw = await redis_client.get(smart_meta_key)
                if raw:
                    smart_metadata = json.loads(raw)
        except Exception:
            pass

        if smart_metadata:
            return self.aggregate_smart_results(db=db, job=crawl_job, smart_metadata=smart_metadata)
        return self.aggregate_results(db=db, job=crawl_job)

    async def _cleanup_redis(self, crawl_job_id: str) -> None:
        async with get_async_redis() as redis_client:
            await redis_client.delete(
                self.pending_urls_key(crawl_job_id),
                self.inflight_key(crawl_job_id),
                self.site_context_key(crawl_job_id),
                f"sitemap:crawl:{crawl_job_id}:smart_metadata",
            )

    def aggregate_results(self, *, db: Session, job: models.SitemapCrawlJob) -> dict[str, Any]:
        audit_jobs = (
            db.query(models.AuditJob)
            .filter(
                models.AuditJob.sitemap_crawl_job_id == job.id,
                models.AuditJob.status == "succeeded",
            )
            .order_by(models.AuditJob.created_at.asc())
            .all()
        )

        if not audit_jobs:
            return {
                "aggregated_scores": {"geo": None, "seo": None, "aeo": None, "site_health": None},
                "score_distribution": {"80_plus": 0, "60_79": 0, "40_59": 0, "below_40": 0},
                "top_issues": [],
                "worst_pages": [],
                "page_count": 0,
                "generated_at": _utcnow().isoformat(),
            }

        request_ids = [str(job_row.request_id) for job_row in audit_jobs if job_row.request_id]
        audits = (
            db.query(models.Audit).filter(models.Audit.request_id.in_(request_ids)).all()
            if request_ids
            else []
        )
        audit_by_request_id = {str(audit.request_id): audit for audit in audits if audit.request_id}

        geo_values: list[float] = []
        seo_values: list[float] = []
        aeo_values: list[float] = []
        overall_values: list[float] = []
        recommendation_counter: Counter[str] = Counter()
        page_rows: list[dict[str, Any]] = []

        for audit_job in audit_jobs:
            audit = audit_by_request_id.get(str(audit_job.request_id or ""))
            if audit is None:
                continue

            geo = float(audit.geo_score) if isinstance(audit.geo_score, (int, float)) else None
            seo = float(audit.seo_score) if isinstance(audit.seo_score, (int, float)) else None
            aeo = float(audit.aeo_score) if isinstance(audit.aeo_score, (int, float)) else None
            metric_values = [value for value in [geo, seo, aeo] if isinstance(value, float)]
            overall = round(sum(metric_values) / len(metric_values), 2) if metric_values else None

            if geo is not None:
                geo_values.append(geo)
            if seo is not None:
                seo_values.append(seo)
            if aeo is not None:
                aeo_values.append(aeo)
            if overall is not None:
                overall_values.append(overall)

            report = audit.full_report if isinstance(audit.full_report, dict) else {}
            normalized_recommendations = extract_normalized_recommendation_items(report)
            if normalized_recommendations:
                for item in normalized_recommendations:
                    category = (
                        str(item.get("category") or item.get("type") or "general").strip().lower()
                    )
                    if category:
                        recommendation_counter[category] += 1
            else:
                recommendations = report.get("recommendations")
                if isinstance(recommendations, list):
                    for item in recommendations:
                        if not isinstance(item, dict):
                            continue
                        category = (
                            str(item.get("category") or item.get("type") or "general")
                            .strip()
                            .lower()
                        )
                        if category:
                            recommendation_counter[category] += 1

            page_rows.append(
                {
                    "url": audit.url,
                    "geo": geo,
                    "seo": seo,
                    "aeo": aeo,
                    "overall": overall,
                    "page_type": _extract_page_type(audit),
                }
            )

        distribution = {"80_plus": 0, "60_79": 0, "40_59": 0, "below_40": 0}
        for value in overall_values:
            if value >= 80:
                distribution["80_plus"] += 1
            elif value >= 60:
                distribution["60_79"] += 1
            elif value >= 40:
                distribution["40_59"] += 1
            else:
                distribution["below_40"] += 1

        top_issues = [
            {"category": category, "count": count}
            for category, count in recommendation_counter.most_common(5)
        ]

        worst_pages = sorted(
            [row for row in page_rows if isinstance(row.get("overall"), (int, float))],
            key=lambda row: float(row["overall"]),
        )[:10]

        best_pages = sorted(
            [row for row in page_rows if isinstance(row.get("overall"), (int, float))],
            key=lambda row: float(row["overall"]),
            reverse=True,
        )[:5]

        # Page-type breakdown: average scores per page type
        def _avg(values: list[float]) -> float | None:
            return round(sum(values) / len(values), 2) if values else None

        page_type_scores: dict[str, dict[str, list[float]]] = {}
        for row in page_rows:
            ptype = row.get("page_type") or "generic"
            if ptype not in page_type_scores:
                page_type_scores[ptype] = {"geo": [], "seo": [], "aeo": [], "overall": []}
            for key in ("geo", "seo", "aeo", "overall"):
                if isinstance(row.get(key), (int, float)):
                    page_type_scores[ptype][key].append(float(row[key]))

        page_type_summary = {}
        for ptype, scores in sorted(page_type_scores.items()):
            page_type_summary[ptype] = {
                "count": len(scores.get("overall", []))
                or sum(len(v) for v in scores.values()) // 4
                or 1,
                "avg_geo": _avg(scores["geo"]),
                "avg_seo": _avg(scores["seo"]),
                "avg_aeo": _avg(scores["aeo"]),
                "avg_overall": _avg(scores["overall"]),
            }

        # Site-wide insights
        site_insights = _build_site_insights(
            page_rows=page_rows,
            recommendation_counter=recommendation_counter,
            page_type_summary=page_type_summary,
        )

        return {
            "aggregated_scores": {
                "geo": _avg(geo_values),
                "seo": _avg(seo_values),
                "aeo": _avg(aeo_values),
                "site_health": _avg(overall_values),
            },
            "score_distribution": distribution,
            "top_issues": top_issues,
            "worst_pages": worst_pages,
            "best_pages": best_pages,
            "page_type_breakdown": page_type_summary,
            "site_insights": site_insights,
            "page_count": len(page_rows),
            "generated_at": _utcnow().isoformat(),
        }

    # ------------------------------------------------------------------ #
    #  Smart Sample Crawl
    # ------------------------------------------------------------------ #

    async def estimate_smart_crawl(
        self,
        *,
        sitemap_url: str,
        max_urls: int = 500,
        max_per_type: int = 2,
        max_total: int = 15,
    ) -> dict[str, Any]:
        """Parse sitemap and return a smart crawl plan with cost estimate."""
        from services.page_type_detector import build_smart_crawl_plan

        urls = await self.parse_sitemap(sitemap_url, max_urls=max_urls)
        plan = build_smart_crawl_plan(
            urls,
            max_per_type=max_per_type,
            max_total=max_total,
        )
        per_url_credit_cost = calculate_audit_credit_cost(
            provider=self.provider,
            tier=self.tier,
            entities_count=0,
        )
        plan["per_url_credit_cost"] = per_url_credit_cost
        plan["estimated_credit_cost"] = plan["sampled_urls_count"] * per_url_credit_cost
        return plan

    async def start_smart_crawl(
        self,
        *,
        db: Session,
        user: models.User,
        project: models.Project,
        sitemap_url: str,
        max_urls: int = 500,
        max_per_type: int = 2,
        max_total: int = 15,
    ) -> models.SitemapCrawlJob:
        """Start a smart sample crawl that audits representative pages per type."""
        from services.page_type_detector import (
            build_site_structure_summary,
            detect_page_type,
            select_representative_urls,
        )

        crawl_job = models.SitemapCrawlJob(
            id=str(uuid4()),
            project_id=project.id,
            user_id=user.id,
            sitemap_url=sitemap_url,
            status="parsing",
            completed_urls=0,
            failed_urls=0,
            credits_consumed=0,
            schema_version="1",
        )
        db.add(crawl_job)
        db.commit()
        db.refresh(crawl_job)

        try:
            all_urls = await self.parse_sitemap(sitemap_url=sitemap_url, max_urls=max_urls)
        except Exception as exc:
            crawl_job.status = "failed"
            crawl_job.error = str(exc)
            crawl_job.completed_at = _utcnow()
            db.add(crawl_job)
            db.commit()
            db.refresh(crawl_job)
            raise

        if not all_urls:
            crawl_job.status = "failed"
            crawl_job.error = "No crawlable page URLs were found in this sitemap."
            crawl_job.completed_at = _utcnow()
            db.add(crawl_job)
            db.commit()
            db.refresh(crawl_job)
            raise HTTPException(status_code=400, detail=crawl_job.error)

        selected = select_representative_urls(
            all_urls,
            max_per_type=max_per_type,
            max_total=max_total,
        )
        sampled_urls: list[str] = []
        for urls_list in selected.values():
            sampled_urls.extend(urls_list)

        if not sampled_urls:
            crawl_job.status = "failed"
            crawl_job.error = "No representative URLs could be selected from this sitemap."
            crawl_job.completed_at = _utcnow()
            db.add(crawl_job)
            db.commit()
            db.refresh(crawl_job)
            raise HTTPException(status_code=400, detail=crawl_job.error)

        # SIGV2-1024: credits are internal soft limits; scan consumption is
        # enforced per dispatched URL by the scan allowance.

        # Store total site URLs count + page type distribution for extrapolation
        all_classified: dict[str, list[str]] = {}
        for url in all_urls:
            ptype = detect_page_type(url)
            all_classified.setdefault(ptype, []).append(url)

        smart_crawl_metadata = {
            "mode": "smart_sample",
            "total_site_urls": len(all_urls),
            "sampled_urls": len(sampled_urls),
            "page_type_distribution": {
                ptype: len(urls_list) for ptype, urls_list in all_classified.items()
            },
            "sampled_per_type": {ptype: urls_list for ptype, urls_list in selected.items()},
        }

        crawl_job.total_urls = len(sampled_urls)
        crawl_job.status = "queuing"
        crawl_job.error = None
        db.add(crawl_job)
        db.commit()

        async with get_async_redis() as redis_client:
            pending_key = self.pending_urls_key(crawl_job.id)
            inflight_key = self.inflight_key(crawl_job.id)
            site_ctx_key = self.site_context_key(crawl_job.id)
            smart_meta_key = f"sitemap:crawl:{crawl_job.id}:smart_metadata"
            pipeline = redis_client.pipeline()
            pipeline.delete(pending_key)
            pipeline.delete(inflight_key)
            pipeline.rpush(pending_key, *sampled_urls)
            pipeline.set(inflight_key, 0, ex=86400)
            pipeline.expire(pending_key, 86400)
            pipeline.set(smart_meta_key, json.dumps(smart_crawl_metadata), ex=86400)
            await pipeline.execute()

            # Build site structure context from ALL URLs (not just sampled)
            try:
                site_pages = [{"url": u, "page_type": detect_page_type(url=u)} for u in all_urls]
                site_summary = build_site_structure_summary(site_pages)
                if site_summary:
                    await redis_client.set(site_ctx_key, site_summary, ex=86400)
            except Exception:
                pass

        await self.queue_next_batch(db=db, crawl_job=crawl_job, max_dispatch=self.max_concurrency)
        db.refresh(crawl_job)
        return crawl_job

    def aggregate_smart_results(
        self,
        *,
        db: Session,
        job: models.SitemapCrawlJob,
        smart_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Aggregate smart crawl results with extrapolation to full site."""
        base_results = self.aggregate_results(db=db, job=job)

        if not smart_metadata:
            return base_results

        total_site_urls = smart_metadata.get("total_site_urls", 0)
        sampled_count = smart_metadata.get("sampled_urls", 0)
        page_type_distribution = smart_metadata.get("page_type_distribution", {})

        # Extrapolation: for each page type, estimate site-wide issues
        page_type_breakdown = base_results.get("page_type_breakdown", {})
        extrapolated_issues: list[dict[str, Any]] = []

        for ptype, type_data in page_type_breakdown.items():
            sampled_in_type = type_data.get("count", 0)
            total_in_type = page_type_distribution.get(ptype, sampled_in_type)

            if sampled_in_type > 0 and total_in_type > sampled_in_type:
                from services.page_type_detector import get_page_type_label

                avg_overall = type_data.get("avg_overall")
                if avg_overall is not None and avg_overall < 60:
                    extrapolated_issues.append(
                        {
                            "page_type": ptype,
                            "label": get_page_type_label(ptype),
                            "sampled": sampled_in_type,
                            "estimated_total": total_in_type,
                            "avg_score": avg_overall,
                            "projected_affected_pages": total_in_type,
                            "confidence": "high" if sampled_in_type >= 2 else "medium",
                            "insight": (
                                f"Based on {sampled_in_type} sampled {get_page_type_label(ptype)} page(s) "
                                f"(avg score: {avg_overall:.1f}/100), an estimated {total_in_type} pages "
                                f"of this type likely share similar issues."
                            ),
                        }
                    )

        base_results["smart_crawl"] = {
            "mode": "smart_sample",
            "total_site_urls": total_site_urls,
            "sampled_urls": sampled_count,
            "coverage_ratio": round(sampled_count / total_site_urls, 3) if total_site_urls else 0,
            "page_type_distribution": page_type_distribution,
            "extrapolated_issues": extrapolated_issues,
            "extrapolation_note": (
                f"This smart crawl audited {sampled_count} representative pages out of "
                f"{total_site_urls} total site pages. Findings are extrapolated to "
                f"pages of the same type based on template similarity."
            ),
        }

        return base_results

    async def _queue_completion_email(
        self, *, db: Session, crawl_job: models.SitemapCrawlJob
    ) -> None:
        project = db.query(models.Project).filter(models.Project.id == crawl_job.project_id).first()
        if project is None or project.workspace is None or project.workspace.owner is None:
            return
        owner = project.workspace.owner
        if not owner.email:
            return

        report_url = f"/dashboard/projects/{project.id}/site-crawl?jobId={crawl_job.id}"
        await EmailService(db).send_sitemap_crawl_complete_email(
            email=owner.email,
            workspace_name=project.workspace.name,
            project_name=project.name,
            sitemap_url=crawl_job.sitemap_url,
            total_urls=int(crawl_job.total_urls or 0),
            completed_urls=int(crawl_job.completed_urls or 0),
            failed_urls=int(crawl_job.failed_urls or 0),
            report_url=report_url,
            user_id=owner.id,
            workspace_id=project.workspace_id,
            correlation_id=f"sitemap-crawl:{crawl_job.id}",
        )
