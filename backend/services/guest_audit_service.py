"""Guest audit execution pipeline.

Extracted from ``routers/api_router.py`` so the exact same pipeline can run in
two places:

* the legacy synchronous ``POST /api/v1/guest-audit`` endpoint, which Signal's
  own marketing page still calls;
* the queued public job runner behind ``POST /api/v1/public/guest-audit``,
  which the marketing site calls. An audit takes tens of seconds, which is
  longer than the edge proxy will hold a connection open, so the public path
  runs the pipeline in the audit worker and the caller polls for the result.

Nothing here is guest-specific security policy: SSRF validation lives in
``services/url_validation.py`` (every outbound fetch on this path goes through
``safe_async_fetch``, which revalidates every redirect hop), and rate limiting
and the output allowlist live in ``services/guest_audit_public.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Final

import jwt
from sqlalchemy.orm import Session

import models
from core.config import settings
from app.services.aeo.structure_service import analyze_json_ld_structure
from score_utils import DeterministicScoringEngine, calculate_deterministic_scores
from services.ai_client import AIClient
from services.audit_feature_gating_service import build_lock_metadata
from services.network_analyzer import NetworkAnalysisService
from services.performance import PerformanceService
from services.scraper import ScraperService

logger = logging.getLogger(__name__)

JWT_SECRET_KEY = settings.JWT_SECRET_KEY

# The capability each guest lock section is gated on. Every value must be a
# key that exists in ``CAPABILITY_MATRIX``; the required plan shown to a
# prospect is then derived from ``MINIMUM_PLAN_BY_FEATURE`` rather than
# written out here. ``test_guest_audit_lock_metadata.py`` fails if a key
# drifts away from the matrix.
GUEST_LOCKED_SECTION_CAPABILITIES: Final[dict[str, str]] = {
    "geo": "geo",
    "aeo": "aeo",
    "competitors": "has_competitor_analysis",
    "entities": "entity_authority",
    # The hallucination / multi-agent review payload is gated on
    # ``has_brand_integrity_guardrails`` everywhere else: see
    # ``audit_feature_gating_service._lock_brand_integrity``, which is what
    # clears ``payload["hallucination"]`` for an under-entitled plan.
    "hallucinations": "has_brand_integrity_guardrails",
    "export": "has_pdf_audit_reports",
}

# Transparent 1x1 PNG, a harmless placeholder for the AI audit payload schema.
PLACEHOLDER_SCREENSHOT_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)

scraper_service = ScraperService()
ai_client = AIClient()
performance_service = PerformanceService()
network_service = NetworkAnalysisService()


def build_degradation_report(
    *,
    target_url: str | None,
    scrape_method: str | None,
    scrape_succeeded: bool,
    screenshot_captured: bool,
    performance_metrics: dict[str, Any] | None,
    ai_analysis_available: bool,
) -> dict[str, Any]:
    """Describe how complete this run actually was.

    A free audit is a first impression, so a run that scored low because a
    collector was unavailable must not be presented as if it were a clean
    measurement. Firecrawl credits being exhausted, for example, drops the
    scrape to a plain HTTP fetch with no JavaScript rendering, which reliably
    understates a client-rendered site. Same spirit as ``visibility_measured``
    in the GEO path: report that the measurement was partial instead of
    quietly returning a worse number.
    """
    reasons: list[dict[str, str]] = []

    if target_url:
        if not scrape_succeeded:
            reasons.append(
                {
                    "code": "content_unavailable",
                    "message": (
                        "The page content could not be retrieved, so the content based "
                        "signals were not measured."
                    ),
                }
            )
        elif scrape_method and scrape_method != "firecrawl":
            reasons.append(
                {
                    "code": "javascript_not_rendered",
                    "message": (
                        "The page was read with a plain HTTP fetch without running "
                        "JavaScript, so content rendered in the browser was not seen. "
                        "Scores are likely understated."
                    ),
                }
            )

        performance_status = str((performance_metrics or {}).get("status") or "").lower()
        if performance_status in {"error", "skipped", "unavailable"}:
            reasons.append(
                {
                    "code": "performance_unavailable",
                    "message": (
                        "Core Web Vitals were not available for this URL, so the "
                        "technical performance signal was not measured."
                    ),
                }
            )

    if not ai_analysis_available:
        reasons.append(
            {
                "code": "ai_analysis_unavailable",
                "message": (
                    "The AI analysis did not complete, so only deterministic signals "
                    "were scored."
                ),
            }
        )

    return {
        "fully_measured": not reasons,
        "content_source": scrape_method or ("none" if target_url else "not_applicable"),
        "javascript_rendered": bool(scrape_method == "firecrawl"),
        "screenshot_captured": bool(screenshot_captured),
        "ai_analysis_available": bool(ai_analysis_available),
        "reasons": reasons,
    }


def _build_guest_target_context_markdown(
    *,
    target_type: str,
    target_name: str | None,
    target_url: str | None,
    target_metadata: dict[str, Any],
) -> str:
    lines: list[str] = [
        "# Guest audit target context",
        f"- Target type: {target_type}",
    ]
    if target_name:
        lines.append(f"- Target name: {target_name}")
    if target_url:
        lines.append(f"- Target URL: {target_url}")
    if target_metadata:
        lines.append("## Target metadata")
        for key in sorted(target_metadata.keys()):
            value = target_metadata.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                serialized = json.dumps(value)
            else:
                serialized = json.dumps(value, ensure_ascii=False)
            lines.append(f"- {key}: {serialized}")
    lines.append("")
    if target_type == "brand" and not target_url:
        lines.append(
            "This is a BRAND-ONLY audit, NO website URL was provided. "
            "Do NOT recommend website-specific technical actions (meta tags, page speed, CLS/LCP, "
            "canonical URLs, alt text, internal linking, HTTP/2, robots.txt, HTTPS). "
            "Focus on: Knowledge Graph optimization, entity authority, brand SERP management, "
            "AI engine visibility, citation strategies, and content authority signals. "
            "Provide a concise GEO and AEO-oriented brand assessment suitable for a guest report."
        )
    else:
        lines.append(
            "Provide a concise SEO, GEO, and AEO-oriented assessment suitable for a guest report."
        )
    return "\n".join(lines)


async def run_guest_audit(
    db: Session,
    *,
    audit_target_type: str,
    target_url: str | None,
    target_name: str | None,
    target_metadata: dict[str, Any] | None = None,
    email: str | None = None,
    request_id: str | None = None,
    ip_hash: str,
    user_agent_hash: str | None = None,
    referrer: str | None = None,
) -> dict[str, Any]:
    """Run the guest audit pipeline and persist the claimable record.

    Returns the full internal guest payload. Callers serving an anonymous
    client must project it through
    ``services.guest_audit_public.project_public_result`` first.
    """
    resolved_target_type = audit_target_type
    resolved_target_url = target_url
    resolved_target_name = target_name or resolved_target_url or ""
    resolved_target_metadata = dict(target_metadata) if isinstance(target_metadata, dict) else {}

    # --- 1. Scrape page content + fetch performance/network in parallel (URL targets only) ---
    markdown_content = None
    screenshot_b64 = None
    performance_metrics: dict[str, Any] = {
        "status": "skipped",
        "performance_score": 0,
        "largest_contentful_paint": None,
        "cumulative_layout_shift": None,
        "seo_audits": [],
    }
    network_data: dict[str, Any] = {
        "http_version": "Unknown",
        "supports_http2": False,
        "supports_http3": False,
        "supports_http3_inferred": False,
    }

    raw_html_content: str | None = None
    scrape_method: str | None = None

    if resolved_target_url:
        scraper_task = asyncio.ensure_future(
            scraper_service.get_page_content_and_screenshot(resolved_target_url)
        )
        perf_task = asyncio.ensure_future(
            performance_service.get_performance_metrics(resolved_target_url, include_seo=True)
        )
        net_task = asyncio.ensure_future(
            network_service.analyze_network_protocols(resolved_target_url)
        )

        # Lightweight HTML fetch for JSON-LD schema extraction
        async def _fetch_html_for_schema(url: str) -> str | None:
            try:
                from services.url_validation import safe_async_fetch

                resp = await safe_async_fetch(url, method="GET", timeout=10.0)
                ct = resp.headers.get("content-type", "")
                if "html" in ct:
                    return resp.text
            except Exception:
                pass
            return None

        html_task = asyncio.ensure_future(_fetch_html_for_schema(resolved_target_url))

        scraped_data, fetched_performance, fetched_network, fetched_html = await asyncio.gather(
            scraper_task,
            perf_task,
            net_task,
            html_task,
            return_exceptions=True,
        )

        if isinstance(fetched_performance, Exception):
            logger.warning("Guest audit performance fetch failed: %s", fetched_performance)
            performance_metrics = {"status": "error", "performance_score": 0, "seo_audits": []}
        elif isinstance(fetched_performance, dict):
            performance_metrics = fetched_performance

        if isinstance(fetched_network, Exception):
            logger.warning("Guest audit network fetch failed: %s", fetched_network)
        elif isinstance(fetched_network, dict):
            network_data = fetched_network

        if not isinstance(fetched_html, Exception) and isinstance(fetched_html, str):
            raw_html_content = fetched_html

        if not isinstance(scraped_data, Exception) and isinstance(scraped_data, dict):
            scrape_method = str(scraped_data.get("scrape_method") or "") or None
            if scraped_data.get("success_status"):
                markdown_content = scraped_data.get("markdown_content")
                screenshot_b64 = scraped_data.get("screenshot_base64")
            else:
                logger.warning("Guest audit scraper returned error: %s", scraped_data.get("error"))
        elif isinstance(scraped_data, Exception):
            logger.warning("Guest audit scraper failed: %s", scraped_data)

    # --- 2. Call AI for analysis (google/fast, cheapest tier) ---
    ai_analysis = None
    seo_score = 0.0
    geo_score = 0.0
    aeo_score = 0.0
    seo_recommendations: list[str] = []
    aeo_recommendations: list[str] = []
    ai_summary = (
        "Basic performance and network analysis completed. Sign in for the full AI-powered audit."
    )
    detailed_seo_recommendations: list[dict] = []
    aeo_teaser = ""
    ai_seo_findings: list[dict] = []
    ai_geo_findings: list[dict] = []
    ai_aeo_findings: list[dict] = []
    ai_entities: list[dict] = []
    ai_competitors: list[dict] = []
    scrape_metadata: dict[str, Any] = {}

    ai_context = markdown_content or _build_guest_target_context_markdown(
        target_type=resolved_target_type,
        target_name=resolved_target_name or None,
        target_url=resolved_target_url,
        target_metadata=resolved_target_metadata,
    )
    try:
        # Build context payload for brand-no-URL so AI engine knows the audit mode
        guest_context_payload: dict[str, Any] | None = None
        guest_screenshot = screenshot_b64 or PLACEHOLDER_SCREENSHOT_BASE64
        if resolved_target_type == "brand" and not resolved_target_url:
            guest_context_payload = {
                "audit_target_type": "brand",
                "target_name": resolved_target_name,
                "scrape_succeeded": False,
            }
            if resolved_target_metadata:
                guest_context_payload["target_metadata"] = resolved_target_metadata
            # Don't send placeholder screenshot for brand-no-URL, it misleads the AI
            guest_screenshot = screenshot_b64  # None if no URL was scraped

        ai_response = await ai_client.generate_audit(
            provider="google",
            tier="fast",
            content=ai_context[:12000],
            screenshot_base64=guest_screenshot,
            network_data=network_data if isinstance(network_data, dict) else {},
            category=None,
            market=None,
            query_type=None,
            context_payload=guest_context_payload,
        )

        if "error" not in ai_response:
            ai_analysis = ai_response.get("analysis", {})
            if isinstance(ai_analysis, dict):
                ai_summary = (
                    ai_analysis.get("intelligence_summary")
                    or ai_analysis.get("summary")
                    or ai_summary
                )

                detailed_seo = ai_analysis.get("detailed_recommendations") or ai_analysis.get(
                    "detailed_seo_recommendations"
                )
                if isinstance(detailed_seo, list):
                    detailed_seo_recommendations = detailed_seo

                teaser = ai_analysis.get("aeo_teaser")
                if teaser:
                    aeo_teaser = teaser

                # Extract per-dimension findings from canonical response
                raw_seo_findings = ai_analysis.get("seo_findings", [])
                if isinstance(raw_seo_findings, list):
                    ai_seo_findings = [f for f in raw_seo_findings if isinstance(f, dict)]
                raw_geo_findings = ai_analysis.get("geo_findings", [])
                if isinstance(raw_geo_findings, list):
                    ai_geo_findings = [f for f in raw_geo_findings if isinstance(f, dict)]
                raw_aeo_findings = ai_analysis.get("aeo_findings", [])
                if isinstance(raw_aeo_findings, list):
                    ai_aeo_findings = [f for f in raw_aeo_findings if isinstance(f, dict)]

                # Extract entities and competitors from canonical response
                raw_entities = ai_analysis.get("entities", [])
                if isinstance(raw_entities, list):
                    ai_entities = [e for e in raw_entities if isinstance(e, dict)]
                raw_competitors = ai_analysis.get("competitors", [])
                if isinstance(raw_competitors, list):
                    ai_competitors = [c for c in raw_competitors if isinstance(c, dict)]
                # Also try competitive.benchmark.rows shape
                if not ai_competitors:
                    competitive = ai_analysis.get("competitive", {})
                    if isinstance(competitive, dict):
                        benchmark = competitive.get("benchmark", {})
                        if isinstance(benchmark, dict):
                            rows = benchmark.get("rows", [])
                            if isinstance(rows, list):
                                ai_competitors = [r for r in rows if isinstance(r, dict)]

                # Extract SEO recommendations from findings
                if ai_seo_findings:
                    seo_recommendations = [
                        finding.get("description", "")
                        for finding in ai_seo_findings
                        if isinstance(finding, dict)
                        and finding.get("severity") in ("critical", "warning")
                    ][:8]
                elif detailed_seo_recommendations:
                    seo_recommendations = [
                        rec.get("finding", "") or rec.get("title", "")
                        for rec in detailed_seo_recommendations
                    ]
                if not seo_recommendations:
                    seo_recommendations = (ai_analysis.get("recommendations") or [])[:5]

                # Extract AEO recommendations from findings
                raw_aeo = ai_analysis.get("aeo_score")
                if isinstance(raw_aeo, dict):
                    aeo_recommendations = (raw_aeo.get("recommendations") or [])[:3]
                if ai_aeo_findings and not aeo_recommendations:
                    aeo_recommendations = [
                        finding.get("description", "")
                        for finding in ai_aeo_findings
                        if isinstance(finding, dict)
                    ][:3]

                # Build scrape_metadata from scraped data for scoring engine
                if markdown_content:
                    raw_meta = (
                        scraped_data.get("metadata", {})
                        if isinstance(scraped_data, dict)
                        and isinstance(scraped_data.get("metadata"), dict)
                        else {}
                    )
                    scrape_metadata = {
                        **raw_meta,
                        "url": raw_meta.get("url") or resolved_target_url or "",
                    }
        else:
            logger.warning("Guest audit AI call returned error: %s", ai_response.get("error"))
    except Exception as exc:
        logger.warning("Guest audit AI call failed, falling back to perf-only: %s", exc)

    # --- 2b. Compute real deterministic scores ---
    # Extract schema types from raw HTML (same approach as full audit)
    schema_analysis: dict[str, Any] | None = None
    if raw_html_content:
        try:
            schema_structure = analyze_json_ld_structure(raw_html_content)
            detected_types = schema_structure.get("detected_schema_types", [])
            if detected_types:
                schema_analysis = {
                    "detected_schema_types": detected_types,
                    "coverage_percent": schema_structure.get("coverage_percent", 0),
                    "coverage_by_type": schema_structure.get("coverage_by_type", {}),
                }
        except Exception:
            logger.debug("Guest audit JSON-LD extraction failed, falling back to AI schema")

    # Fall back to AI-derived schema data if structure analysis found nothing
    if not schema_analysis and isinstance(ai_analysis, dict):
        ai_schema = ai_analysis.get("schema_analysis") or ai_analysis.get("aeo", {})
        if isinstance(ai_schema, dict) and ai_schema.get("schema_health"):
            schema_analysis = {
                "detected_schema_types": list(
                    (ai_schema.get("schema_health", {}).get("coverage_by_type", {}) or {}).keys()
                ),
                "coverage_percent": ai_schema.get("schema_health", {}).get("score", 0),
            }

    # --- Collect brand signals for brand-no-URL guest audits ---
    guest_brand_signals: dict[str, Any] | None = None
    if resolved_target_type == "brand" and not resolved_target_url:
        try:
            from services.brand_signal_collector_service import BrandSignalCollectorService

            brand_signal_service = BrandSignalCollectorService()
            guest_brand_signals = await brand_signal_service.collect_brand_signals(
                brand_name=resolved_target_name or "",
                category=None,
                market=None,
                domain=resolved_target_metadata.get("domain")
                or resolved_target_metadata.get("website"),
            )
            logger.info(
                "Guest brand signals collected for %s: %d signals, presence_score=%.1f",
                resolved_target_name,
                guest_brand_signals.get("summary", {}).get("signals_collected", 0),
                guest_brand_signals.get("summary", {}).get("brand_presence_score", 0),
            )
        except Exception as exc:
            logger.warning(
                "Guest brand signal collection failed for %s: %s", resolved_target_name, exc
            )
            guest_brand_signals = None

    # Build AI analysis quality metadata for score floor calculation
    _ai_findings_meta: dict[str, Any] | None = None
    if resolved_target_type == "brand" and not resolved_target_url:
        _ai_findings_meta = {
            "seo_findings_count": len(ai_seo_findings),
            "geo_findings_count": len(ai_geo_findings),
            "aeo_findings_count": len(ai_aeo_findings),
            "summary_length": len(ai_summary) if isinstance(ai_summary, str) else 0,
            "recommendations_count": len(seo_recommendations)
            + len(aeo_recommendations)
            + len(detailed_seo_recommendations),
        }

    det_scores = calculate_deterministic_scores(
        performance_metrics=performance_metrics if isinstance(performance_metrics, dict) else None,
        schema_analysis=schema_analysis,
        scrape_metadata=scrape_metadata or None,
        network_data=network_data if isinstance(network_data, dict) else None,
        content=markdown_content,
        seo_findings=ai_seo_findings or None,
        geo_findings=ai_geo_findings or None,
        aeo_findings=ai_aeo_findings or None,
        brand_name=resolved_target_name if resolved_target_type == "brand" else None,
        brand_signals=guest_brand_signals,
        scrape_succeeded=bool(resolved_target_url and markdown_content),
        ai_findings_meta=_ai_findings_meta,
    )

    seo_score = det_scores.get("seo_score", 0.0)
    geo_score = det_scores.get("geo_score", 0.0)
    aeo_score = det_scores.get("aeo_score", 0.0)

    # --- 3. Build SEO improvements from PageSpeed (always available) ---
    psi_seo_improvements: list[str] = []
    seo_audits = (
        performance_metrics.get("seo_audits", []) if isinstance(performance_metrics, dict) else []
    )
    for audit in (seo_audits or [])[:5]:
        title = audit.get("title", "SEO improvement")
        description = audit.get("description", "")
        psi_seo_improvements.append(f"{title}. {description}".strip() if description else title)

    # Merge AI recommendations with PSI recommendations (no duplicates)
    all_seo = seo_recommendations[:]
    for psi_rec in psi_seo_improvements:
        if psi_rec and psi_rec not in all_seo:
            all_seo.append(psi_rec)
    all_seo = all_seo[:8]  # Cap at 8 recommendations

    # --- 4. Build insights ---
    insights = []
    perf_score_value = (
        performance_metrics.get("performance_score", 0)
        if isinstance(performance_metrics, dict)
        else 0
    )
    if (
        resolved_target_url
        and isinstance(perf_score_value, (int, float))
        and perf_score_value >= 90
    ):
        insights.append("Performance looks excellent with a top-tier score.")
    elif (
        resolved_target_url
        and isinstance(perf_score_value, (int, float))
        and perf_score_value >= 70
    ):
        insights.append("Performance is solid, but there is room for optimization.")
    elif resolved_target_url:
        insights.append("Performance needs improvement to meet modern UX benchmarks.")
    else:
        insights.append(
            "No website URL was provided; technical performance and protocol checks were skipped."
        )

    if resolved_target_url:
        if isinstance(network_data, dict) and network_data.get("supports_http2"):
            insights.append("HTTP/2 support detected, which improves loading efficiency.")
        else:
            insights.append("HTTP/2 was not detected; consider enabling it with your host.")
        if isinstance(network_data, dict) and network_data.get("supports_http3_inferred"):
            insights.append(
                "HTTP/3 support is advertised, which boosts resilience on mobile networks."
            )
    else:
        insights.append(
            "Brand mode can include technical diagnostics when you optionally provide a website URL."
        )

    # AEO placeholder recommendations (always present as freemium teaser)
    if not aeo_recommendations:
        if resolved_target_type == "brand" and not resolved_target_url:
            aeo_recommendations = [
                "Build a structured knowledge base (FAQ, About) so AI engines can cite your brand accurately.",
                "Strengthen entity authority through consistent brand mentions across authoritative third-party sources.",
            ]
        else:
            aeo_recommendations = [
                "Add JSON-LD structured data that matches visible content.",
                "Strengthen people-first signals with clear authorship and complete answers.",
            ]

    rounded_seo_score = int(round(seo_score))
    rounded_geo_score = int(round(geo_score))
    rounded_aeo_score = int(round(aeo_score))
    rounded_perf_score = (
        int(round(float(perf_score_value))) if isinstance(perf_score_value, (int, float)) else 0
    )
    overall_score = int(
        round(
            DeterministicScoringEngine.calculate_overall_score(
                {"seo": seo_score, "geo": geo_score, "aeo": aeo_score}
            )
        )
    )

    # Map AI guest recommendations to the frontend-expected contract shape.
    mapped_recommendations = [
        {
            "source": rec.get("agent", "AI Analysis"),
            "priority": rec.get("severity", "Warning").capitalize()
            if rec.get("severity")
            else "Warning",
            "title": rec.get("finding") or rec.get("title", ""),
            "description": rec.get("why_it_matters") or rec.get("description", ""),
            "implementation": rec.get("fix") or rec.get("implementation", ""),
        }
        for rec in detailed_seo_recommendations
        if isinstance(rec, dict)
    ]

    # Build structured findings with gating for guest mode (S-B2)
    geo_recommendations: list[str] = []
    if ai_geo_findings:
        geo_recommendations = [
            f.get("description", "")
            for f in ai_geo_findings
            if isinstance(f, dict) and f.get("severity") in ("critical", "warning")
        ][:5]

    structured_findings = {
        "seo_findings": ai_seo_findings,
        "geo_findings": {
            "preview": ai_geo_findings[:2],
            "total_count": len(ai_geo_findings),
            "locked": True,
        },
        "aeo_findings": {
            "preview": ai_aeo_findings[:2],
            "total_count": len(ai_aeo_findings),
            "locked": True,
        },
        "entity_summary": {
            "count": len(ai_entities),
            "top_names": [e.get("name", "") for e in ai_entities[:3] if isinstance(e, dict)],
            "locked": True,
        },
    }

    # Build locked_sections metadata for frontend gating. Every required plan
    # is derived from MINIMUM_PLAN_BY_FEATURE via build_lock_metadata, so the
    # upgrade promise a prospect is shown always matches what the plan
    # actually grants.
    section_details = {
        "geo": f"{len(ai_geo_findings)} GEO findings discovered. Sign up to see the full breakdown.",
        "aeo": f"{len(ai_aeo_findings)} AEO findings discovered. Sign up to see the full breakdown.",
        "competitors": (
            f"{len(ai_competitors)} competitors discovered. Sign up to unlock competitor radar."
        ),
        "entities": f"{len(ai_entities)} entities detected. Sign up to see authority & gaps.",
        "hallucinations": "Multi-agent review not available in guest mode.",
        "export": "PDF export is available after you sign up.",
    }
    locked_sections = {
        section_key: build_lock_metadata(
            capability_key=GUEST_LOCKED_SECTION_CAPABILITIES[section_key],
            detail=detail,
            lock_origin="guest",
        )
        for section_key, detail in section_details.items()
    }

    # --- Persist guest audit record & generate claim token ---
    guest_record = models.GuestAuditRecord(
        ip_hash=ip_hash,
        target_url=resolved_target_url,
        target_name=resolved_target_name or None,
        audit_target_type=resolved_target_type,
        seo_score=rounded_seo_score,
        geo_score=rounded_geo_score,
        aeo_score=rounded_aeo_score,
        overall_score=overall_score,
        findings_summary=structured_findings,
        entity_count=len(ai_entities),
        competitor_count=len(ai_competitors),
        claim_token="",  # placeholder, set after flush
        email=email,
        referrer=referrer,
        user_agent_hash=user_agent_hash,
        request_id=request_id,
    )
    db.add(guest_record)
    db.flush()  # get guest_record.id

    claim_token_payload = {
        "guest_audit_id": guest_record.id,
        "exp": datetime.now(timezone.utc) + timedelta(days=30),
        "type": "guest_audit_claim",
    }
    claim_token = jwt.encode(claim_token_payload, JWT_SECRET_KEY, algorithm="HS256")
    guest_record.claim_token = claim_token
    db.commit()

    # Queue follow-up email if an email was captured
    guest_email = email
    if guest_email:
        try:
            from services.email_service import EmailService
            from services.email_templates import app_base_url

            EmailService(db).queue_template_email(
                to_email=guest_email,
                template_key="guest_audit.followup",
                context={
                    "target_name": resolved_target_name or resolved_target_url or "your site",
                    "seo_score": rounded_seo_score,
                    "geo_score": rounded_geo_score,
                    "aeo_score": rounded_aeo_score,
                    "overall_score": overall_score,
                    "signup_url": f"{app_base_url()}/register?guest_audit_token={claim_token}",
                },
                correlation_id=f"guest_audit.followup:{guest_record.id}",
                commit=True,
            )
        except Exception:
            logger.error(
                "Failed to queue guest_audit.followup email for guest audit %s",
                guest_record.id,
                exc_info=True,
            )

    degradation = build_degradation_report(
        target_url=resolved_target_url,
        scrape_method=scrape_method,
        scrape_succeeded=bool(markdown_content),
        screenshot_captured=bool(screenshot_b64),
        performance_metrics=performance_metrics if isinstance(performance_metrics, dict) else None,
        ai_analysis_available=isinstance(ai_analysis, dict) and bool(ai_analysis),
    )

    return {
        "degradation": degradation,
        "url": resolved_target_url or "",
        "target": {
            "type": resolved_target_type,
            "name": resolved_target_name or None,
            "url": resolved_target_url,
            "metadata": resolved_target_metadata,
        },
        "entity": resolved_target_name or "",
        "schema_version": "canonical",
        "site": {
            "url": resolved_target_url or "",
            "market": "global",
            "language": "en",
        },
        "seo": {
            "score": rounded_seo_score,
            "suggestions": all_seo,
            "audits": seo_audits or [],
            "structured_data_detected": (
                performance_metrics.get("structured_data_detected")
                if isinstance(performance_metrics, dict)
                else None
            ),
            "status": (
                performance_metrics.get("seo_status")
                if isinstance(performance_metrics, dict)
                else None
            ),
        },
        "geo": {
            "score": rounded_geo_score,
            "suggestions": geo_recommendations,
            "content_citability": det_scores.get("geo_breakdown", {})
            .get("components", {})
            .get("content_citability"),
            "source_authority": det_scores.get("geo_breakdown", {})
            .get("components", {})
            .get("source_authority"),
            "entity_clarity": det_scores.get("geo_breakdown", {})
            .get("components", {})
            .get("entity_clarity"),
            "brand_citation": det_scores.get("geo_breakdown", {})
            .get("components", {})
            .get("brand_citation"),
            "citation_share": det_scores.get("geo_breakdown", {})
            .get("components", {})
            .get("content_citability"),
        },
        "aeo": {
            "score": rounded_aeo_score,
            "suggestions": aeo_recommendations,
            "answerability_score": det_scores.get("aeo_breakdown", {})
            .get("components", {})
            .get("llm_schema_readiness"),
            "snippet_formatting": det_scores.get("aeo_breakdown", {})
            .get("components", {})
            .get("snippet_formatting"),
            "information_gain": det_scores.get("aeo_breakdown", {})
            .get("components", {})
            .get("information_gain"),
            "semantic_entity_density": det_scores.get("aeo_breakdown", {})
            .get("components", {})
            .get("semantic_entity_density"),
            "schema_health": {
                "score": det_scores.get("aeo_breakdown", {})
                .get("components", {})
                .get("llm_schema_readiness", 0)
            }
            if det_scores.get("aeo_breakdown")
            else None,
        },
        "scores": {
            "seo": rounded_seo_score,
            "geo": rounded_geo_score,
            "aeo": rounded_aeo_score,
            "overall": overall_score,
            "seo_breakdown": det_scores.get("seo_breakdown"),
            "geo_breakdown": det_scores.get("geo_breakdown"),
            "aeo_breakdown": det_scores.get("aeo_breakdown"),
        },
        "performance": performance_metrics,
        "network": network_data,
        "analysis_metadata": {
            "tools_used": [
                {"name": "Gemini Flash 2.5", "task": "Visual & Semantic Analysis"},
                {"name": "Google PageSpeed", "task": "Core Web Vitals & Technicals"},
                {"name": "Network Analyzer", "task": "Protocol & Security Check"},
                {
                    "name": "Deterministic Scoring Engine",
                    "task": "Multi-dimension Score Calibration",
                },
            ]
        },
        "intelligence_summary": ai_summary,
        "detailed_seo_recommendations": mapped_recommendations,
        "aeo_teaser": aeo_teaser,
        "structured_findings": structured_findings,
        "metadata": {
            "created_at": datetime.now(timezone.utc).isoformat() + "Z",
            "plan": "guest",
            "version": "2.0",
            "audit_target_type": resolved_target_type,
            "target_name": resolved_target_name or None,
            "target_url": resolved_target_url,
            "target_metadata": resolved_target_metadata,
            "locked_sections": locked_sections,
            "technical_signals": {
                "performance": {
                    "score": (
                        performance_metrics.get("performance_score")
                        if isinstance(performance_metrics, dict)
                        else 0
                    ),
                    "lcp_ms": (
                        performance_metrics.get("largest_contentful_paint")
                        if isinstance(performance_metrics, dict)
                        else None
                    ),
                    "cls": (
                        performance_metrics.get("cumulative_layout_shift")
                        if isinstance(performance_metrics, dict)
                        else None
                    ),
                },
                "network": {
                    "http_version": (
                        network_data.get("http_version")
                        if isinstance(network_data, dict)
                        else "Unknown"
                    ),
                    "supports_http2": (
                        network_data.get("supports_http2")
                        if isinstance(network_data, dict)
                        else False
                    ),
                    "supports_http3": (
                        network_data.get("supports_http3")
                        if isinstance(network_data, dict)
                        else False
                    ),
                    "supports_http3_inferred": (
                        network_data.get("supports_http3_inferred")
                        if isinstance(network_data, dict)
                        else False
                    ),
                },
            },
            "score_source": "deterministic_matrix",
            "score_version": det_scores.get("version", "3.0"),
        },
        "score_groups": [
            {
                "label": "Technical Setup",
                "score": rounded_perf_score,
                "locked": not bool(resolved_target_url),
            },
            {"label": "SEO Health", "score": rounded_seo_score},
            {"label": "GEO Visibility", "score": rounded_geo_score, "locked": True},
            {"label": "AEO Readiness", "score": rounded_aeo_score, "locked": True},
        ],
        "seo_score": rounded_seo_score,
        "geo_score": rounded_geo_score,
        "aeo_score": rounded_aeo_score,
        "is_locked": True,
        "analysis": {
            "summary": ai_summary,
            "recommendations": all_seo,
            "seo_score": {"score": rounded_seo_score, "recommendations": all_seo},
            "seo_findings": ai_seo_findings,
            "aeo_score": {"score": rounded_aeo_score, "recommendations": aeo_recommendations},
            "aeo_findings": ai_aeo_findings[:2],
            "geo_score": {"score": rounded_geo_score, "recommendations": geo_recommendations},
            "geo_findings": ai_geo_findings[:2],
        },
        "geo_signals": {},
        "aeo_signals": {},
        "hallucination": {
            "threshold": 0.85,
            "total_claims": 0,
            "flagged_claims": 0,
            "claims": [],
            "high_risk_discrepancies": [],
        },
        "competitors": ai_competitors[:3],
        "entities": [
            {"name": e.get("name", ""), "type": e.get("type", "")}
            for e in ai_entities[:5]
            if isinstance(e, dict)
        ],
        "request_id": request_id,
        "insights": insights,
        "seo_improvements": all_seo,
        "aeo_improvements": aeo_recommendations,
        "guest_audit_token": claim_token,
    }
