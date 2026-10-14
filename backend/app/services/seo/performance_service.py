from __future__ import annotations

from typing import Any
import os
import logging
import httpx

from services.observability import describe_http_failure

logger = logging.getLogger(__name__)

LCP_GOOD_THRESHOLD_MS = 2500
LCP_NEEDS_IMPROVEMENT_THRESHOLD_MS = 4000
CLS_GOOD_THRESHOLD = 0.1
CLS_NEEDS_IMPROVEMENT_THRESHOLD = 0.25
FCP_GOOD_THRESHOLD_MS = 1800
FCP_NEEDS_IMPROVEMENT_THRESHOLD_MS = 3000


_METRIC_SPECS: dict[str, dict[str, Any]] = {
    "lcp": {
        "audit_key": "largest-contentful-paint",
        "loading_experience_key": "LARGEST_CONTENTFUL_PAINT_MS",
        "good_threshold": LCP_GOOD_THRESHOLD_MS,
        "needs_improvement_threshold": LCP_NEEDS_IMPROVEMENT_THRESHOLD_MS,
        "unit": "ms",
    },
    "cls": {
        "audit_key": "cumulative-layout-shift",
        "loading_experience_key": "CUMULATIVE_LAYOUT_SHIFT_SCORE",
        "good_threshold": CLS_GOOD_THRESHOLD,
        "needs_improvement_threshold": CLS_NEEDS_IMPROVEMENT_THRESHOLD,
        "unit": "score",
    },
    "fcp": {
        "audit_key": "first-contentful-paint",
        "loading_experience_key": "FIRST_CONTENTFUL_PAINT_MS",
        "good_threshold": FCP_GOOD_THRESHOLD_MS,
        "needs_improvement_threshold": FCP_NEEDS_IMPROVEMENT_THRESHOLD_MS,
        "unit": "ms",
    },
}


def _to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None

    return None


def _extract_metric_value(
    pagespeed_result: dict[str, Any],
    audit_key: str,
    loading_experience_key: str,
    *,
    metric_name: str,
) -> float | None:
    lighthouse_result = pagespeed_result.get("lighthouseResult", {})
    audits = lighthouse_result.get("audits", {})

    numeric_value = _to_float(audits.get(audit_key, {}).get("numericValue"))
    if numeric_value is not None:
        return numeric_value

    loading_experience = pagespeed_result.get("loadingExperience", {})
    loading_metrics = loading_experience.get("metrics", {})
    percentile = _to_float(loading_metrics.get(loading_experience_key, {}).get("percentile"))
    if percentile is not None:
        if metric_name == "cls" and percentile > 1:
            return percentile / 100
        return percentile

    origin_loading_experience = pagespeed_result.get("originLoadingExperience", {})
    origin_metrics = origin_loading_experience.get("metrics", {})
    origin_percentile = _to_float(origin_metrics.get(loading_experience_key, {}).get("percentile"))
    if origin_percentile is None:
        return None

    if metric_name == "cls" and origin_percentile > 1:
        return origin_percentile / 100

    return origin_percentile


def _metric_status(
    value: float | None, good_threshold: float, needs_improvement_threshold: float
) -> str:
    if value is None:
        return "bad"

    if value <= good_threshold:
        return "good"

    if value <= needs_improvement_threshold:
        return "needs_improvement"

    return "bad"


def normalize_core_web_vitals(pagespeed_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    normalized_metrics: dict[str, dict[str, Any]] = {}

    for metric_name, spec in _METRIC_SPECS.items():
        metric_value = _extract_metric_value(
            pagespeed_result=pagespeed_result,
            audit_key=spec["audit_key"],
            loading_experience_key=spec["loading_experience_key"],
            metric_name=metric_name,
        )

        normalized_metrics[metric_name] = {
            "value": metric_value,
            "status": _metric_status(
                value=metric_value,
                good_threshold=spec["good_threshold"],
                needs_improvement_threshold=spec["needs_improvement_threshold"],
            ),
            "target_threshold": spec["good_threshold"],
            "unit": spec["unit"],
        }

    return normalized_metrics


async def fetch_pagespeed_metrics(url: str, strategy: str = "mobile") -> dict[str, Any]:
    """
    Fetches real-time PageSpeed Insights data and pipes it through the core web vitals normalizer.
    """
    api_key = os.getenv("PAGESPEED_API_KEY")
    if not api_key:
        logger.warning("PAGESPEED_API_KEY not found. Returning empty metrics.")
        return {}

    endpoint = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    params = {"url": url, "key": api_key, "strategy": strategy.upper(), "category": "PERFORMANCE"}

    async with httpx.AsyncClient() as client:
        try:
            # Note: We rely on standard httpx error handling here, can be wrapped in a resilience breaker
            response = await client.get(endpoint, params=params, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            return normalize_core_web_vitals(data)
        except Exception as exc:
            # The PageSpeed key travels as the ``key`` query parameter, and httpx puts the
            # full request URL in its exception messages, so never log ``exc`` verbatim.
            logger.error(
                "Error fetching PageSpeed metrics for %s: %s",
                url,
                describe_http_failure(endpoint, exc),
            )
            return {}
