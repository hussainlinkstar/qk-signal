"""Model Lifecycle Monitoring Service

Daily monitor that fetches official provider deprecation / pricing pages,
diffs them against previously stored snapshots, and raises alerts when
content changes or when models used by *this* application appear in
deprecation notices.
"""

from __future__ import annotations

import hashlib
import html
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

import models
from core.config import settings
from services.email_service import EmailService

logger = logging.getLogger(__name__)

# ── Sources to monitor ──────────────────────────────────────────────

MONITOR_SOURCES: list[dict[str, str]] = [
    {
        "provider": "openai",
        "url": "https://developers.openai.com/api/docs/deprecations",
        "page_type": "deprecations",
    },
    {
        "provider": "google",
        "url": "https://ai.google.dev/gemini-api/docs/deprecations",
        "page_type": "deprecations",
    },
    {
        "provider": "anthropic",
        "url": "https://docs.anthropic.com/en/docs/about-claude/model-deprecations",
        "page_type": "deprecations",
    },
    {
        "provider": "perplexity",
        "url": "https://docs.perplexity.ai/changelog",
        "page_type": "deprecations",
    },
    {
        "provider": "bing",
        "url": "https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/model-retirements",
        "page_type": "deprecations",
    },
    {
        "provider": "xai",
        "url": "https://docs.x.ai/changelog",
        "page_type": "deprecations",
    },
    {
        "provider": "deepseek",
        "url": "https://api-docs.deepseek.com/news",
        "page_type": "deprecations",
    },
    {
        "provider": "openai",
        "url": "https://developers.openai.com/api/docs/pricing",
        "page_type": "pricing",
    },
    {
        "provider": "google",
        "url": "https://ai.google.dev/pricing",
        "page_type": "pricing",
    },
    {
        "provider": "anthropic",
        "url": "https://www.anthropic.com/pricing",
        "page_type": "pricing",
    },
    {
        "provider": "perplexity",
        "url": "https://docs.perplexity.ai/guides/pricing",
        "page_type": "pricing",
    },
    {
        "provider": "bing",
        "url": "https://azure.microsoft.com/en-us/pricing/details/cognitive-services/openai-service/",
        "page_type": "pricing",
    },
    {
        "provider": "xai",
        "url": "https://docs.x.ai/docs",
        "page_type": "pricing",
    },
    {
        "provider": "deepseek",
        "url": "https://api-docs.deepseek.com/quick_start/pricing",
        "page_type": "pricing",
    },
]

# Models this app ACTUALLY runs are Bedrock-only (post-cutover). Anchor the
# "is this one of ours?" decision to the configured Bedrock models, not the broad
# historical pricing matrix (which still lists OpenAI/Google models we no longer
# call) — otherwise lifecycle emails fire for providers we don't use.
_BEDROCK_MODEL_SETTINGS = (
    "BEDROCK_SMART_MODEL",
    "BEDROCK_FAST_MODEL",
    "BEDROCK_LITE_MODEL",
    "BEDROCK_EMBEDDING_MODEL",
)


def _bedrock_family_token(model_id: str) -> str:
    """Reduce a Bedrock model id to its family token.

    Strips the leading ``region.provider`` segments (purely-alphabetic, e.g.
    ``eu``/``anthropic``/``amazon``/``zai``), keeping the model name (which may
    itself contain dots, e.g. ``glm-4.7``), then drops the version/date suffix.

    e.g. ``eu.anthropic.claude-sonnet-4-5-20250929-v1:0`` -> ``claude-sonnet-4-5``,
    ``eu.amazon.nova-lite-v1:0`` -> ``nova-lite``, ``zai.glm-4.7`` -> ``glm-4.7``.
    """
    segments = str(model_id or "").strip().lower().split(".")
    while segments and segments[0].isalpha():  # drop region/provider prefixes
        segments.pop(0)
    tail = ".".join(segments)
    tail = re.sub(r":.*$", "", tail)  # drop ":0"
    tail = re.sub(r"-v\d+$", "", tail)  # drop "-v1"
    tail = re.sub(r"-\d{6,8}$", "", tail)  # drop date suffix "-20250929"
    return tail


def _active_bedrock_models() -> set[str]:
    """Family tokens for the models the app actively runs on Bedrock."""
    raw_ids: list[str] = []
    for attr in _BEDROCK_MODEL_SETTINGS:
        value = getattr(settings, attr, None)
        if value:
            raw_ids.append(str(value))
    measurement_map = getattr(settings, "BEDROCK_MEASUREMENT_MODEL_MAP", None)
    if isinstance(measurement_map, dict):
        raw_ids.extend(str(v) for v in measurement_map.values() if v)
    return {fam for fam in (_bedrock_family_token(r) for r in raw_ids) if fam}


def _is_our_model(model_name: str, active_models: set[str]) -> bool:
    """True when an extracted model name maps to a model we run on Bedrock.

    Boundary-aware (exact or ``family-`` prefix) so short tokens never
    false-match (e.g. ``glm-5`` must not match an unrelated name).
    """
    name = (model_name or "").lower()
    for fam in active_models:
        if not fam:
            continue
        if name == fam or name.startswith(fam + "-") or fam.startswith(name + "-"):
            return True
    return False


# Model name patterns per provider
_MODEL_PATTERNS: dict[str, re.Pattern[str]] = {
    "openai": re.compile(r"\b(gpt-[\w.\-]+)", re.IGNORECASE),
    "google": re.compile(r"\b(gemini-[\w.\-]+)", re.IGNORECASE),
    "anthropic": re.compile(r"\b(claude-[\w.\-]+)", re.IGNORECASE),
    "perplexity": re.compile(r"\b(sonar(?:-[\w.\-]+)?)\b", re.IGNORECASE),
    "bing": re.compile(r"\b(gpt-[\w.\-]+)", re.IGNORECASE),
    "xai": re.compile(r"\b(grok-[\w.\-]+)", re.IGNORECASE),
    "deepseek": re.compile(r"\b(deepseek-[\w.\-]+)", re.IGNORECASE),
}

# Lifecycle keywords
_LIFECYCLE_KEYWORDS = re.compile(
    r"\b(deprecat(?:ed|ion|ing)|shutdown|shut\s+down|end[- ]of[- ]life|"
    r"eol|retir(?:ed|ement|ing)|sunset(?:ted|ting)?|removed|"
    r"stable|preview|beta|experimental)\b",
    re.IGNORECASE,
)

# Date patterns (various formats)
_DATE_PATTERN = re.compile(
    r"\b("
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"
    r"|(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"\s+\d{1,2},?\s+\d{4}"
    r")\b",
    re.IGNORECASE,
)


def _strip_html(raw_html: str) -> str:
    """Strip HTML tags and decode entities, returning plain text."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _hash_content(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract_model_references(text: str, provider: str) -> list[dict[str, Any]]:
    """Extract model names, lifecycle keywords, and nearby dates from text."""
    pattern = _MODEL_PATTERNS.get(provider)
    if not pattern:
        return []

    active_models = _active_bedrock_models()
    found: list[dict[str, Any]] = []
    seen_models: set[str] = set()
    for match in pattern.finditer(text):
        model_name = match.group(1).lower().rstrip(".-")
        if model_name in seen_models:
            continue
        seen_models.add(model_name)

        # Extract context window around the match (300 chars each side)
        start = max(0, match.start() - 300)
        end = min(len(text), match.end() + 300)
        context = text[start:end]

        lifecycle_matches = _LIFECYCLE_KEYWORDS.findall(context)
        date_matches = _DATE_PATTERN.findall(context)

        entry: dict[str, Any] = {"model": model_name}
        if lifecycle_matches:
            entry["lifecycle_keywords"] = list(set(kw.lower() for kw in lifecycle_matches))
        if date_matches:
            entry["dates"] = list(set(date_matches))
        entry["is_ours"] = _is_our_model(model_name, active_models)

        found.append(entry)

    return found


def _fetch_page(url: str) -> str | None:
    """Fetch a page using SSRF-safe sync fetch. Returns raw HTML or None."""
    try:
        from services.url_validation import safe_sync_fetch

        resp = safe_sync_fetch(url, timeout=30.0, max_response_bytes=5 * 1024 * 1024)
        if resp.status_code == 200:
            return resp.text
        logger.warning("Non-200 status %s fetching %s", resp.status_code, url)
        return None
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None


def _get_previous_snapshot(
    db: Session, provider: str, source_url: str
) -> models.ModelLifecycleSnapshot | None:
    return (
        db.query(models.ModelLifecycleSnapshot)
        .filter(
            models.ModelLifecycleSnapshot.provider == provider,
            models.ModelLifecycleSnapshot.source_url == source_url,
        )
        .order_by(models.ModelLifecycleSnapshot.fetched_at.desc())
        .first()
    )


def _classify_severity(
    alert_type: str,
    affected_our_models: list[str],
    lifecycle_keywords: list[str],
) -> str:
    """Determine severity: critical if our models are deprecated/shutdown, else warning/info."""
    critical_keywords = {
        "deprecated",
        "deprecation",
        "shutdown",
        "shut down",
        "end-of-life",
        "eol",
        "retired",
        "retirement",
        "removed",
        "sunset",
        "sunsetted",
    }
    has_critical_keyword = bool(set(lifecycle_keywords) & critical_keywords)

    if affected_our_models and has_critical_keyword:
        return "critical"
    if affected_our_models:
        return "warning"
    if alert_type == "page_changed":
        return "info"
    return "warning"


def _build_alerts_from_diff(
    provider: str,
    source_url: str,
    page_type: str,
    prev_models: list[dict[str, Any]] | None,
    curr_models: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare previous and current model extractions, produce alert dicts."""
    alerts: list[dict[str, Any]] = []
    prev_map: dict[str, dict[str, Any]] = {}
    if prev_models:
        for m in prev_models:
            prev_map[m["model"]] = m
    curr_map = {m["model"]: m for m in curr_models}

    # New models appearing on deprecation pages
    for name, info in curr_map.items():
        if name not in prev_map:
            keywords = info.get("lifecycle_keywords", [])
            is_ours = info.get("is_ours", False)
            affected = [name] if is_ours else []
            severity = _classify_severity("model_appeared", affected, keywords)

            keyword_str = ", ".join(keywords) if keywords else "none detected"
            desc = f"Model '{name}' appeared on {provider} {page_type} page with keywords: {keyword_str}."
            if is_ours:
                desc += " THIS MODEL IS USED IN OUR APPLICATION."

            alerts.append(
                {
                    "provider": provider,
                    "alert_type": "model_appeared"
                    if page_type == "deprecations"
                    else "pricing_model_appeared",
                    "severity": severity,
                    "title": f"{'[OUR MODEL] ' if is_ours else ''}New model on {provider} {page_type}: {name}",
                    "description": desc,
                    "affected_models": affected,
                    "details": {"model_info": info, "page_type": page_type},
                    "source_url": source_url,
                }
            )

    # Models whose lifecycle keywords changed
    for name, curr_info in curr_map.items():
        if name in prev_map:
            prev_info = prev_map[name]
            prev_kw = set(prev_info.get("lifecycle_keywords", []))
            curr_kw = set(curr_info.get("lifecycle_keywords", []))
            if curr_kw != prev_kw:
                new_kw = curr_kw - prev_kw
                is_ours = curr_info.get("is_ours", False)
                affected = [name] if is_ours else []
                severity = _classify_severity("lifecycle_change", affected, list(new_kw))

                desc = f"Model '{name}' lifecycle changed on {provider} {page_type}. New keywords: {', '.join(new_kw)}."
                if is_ours:
                    desc += " THIS MODEL IS USED IN OUR APPLICATION."

                alerts.append(
                    {
                        "provider": provider,
                        "alert_type": "lifecycle_change",
                        "severity": severity,
                        "title": f"{'[OUR MODEL] ' if is_ours else ''}Lifecycle change for {name}",
                        "description": desc,
                        "affected_models": affected,
                        "details": {
                            "previous_keywords": sorted(prev_kw),
                            "current_keywords": sorted(curr_kw),
                            "new_keywords": sorted(new_kw),
                        },
                        "source_url": source_url,
                    }
                )

    # Models that disappeared from the page (potentially removed/sunset)
    for name in prev_map:
        if name not in curr_map:
            is_ours = prev_map[name].get("is_ours", False)
            affected = [name] if is_ours else []
            severity = "warning" if is_ours else "info"

            alerts.append(
                {
                    "provider": provider,
                    "alert_type": "model_removed",
                    "severity": severity,
                    "title": f"{'[OUR MODEL] ' if is_ours else ''}Model removed from {provider} {page_type}: {name}",
                    "description": f"Model '{name}' is no longer listed on {provider} {page_type} page.",
                    "affected_models": affected,
                    "details": {"previous_info": prev_map[name]},
                    "source_url": source_url,
                }
            )

    return alerts


def _send_admin_email_alerts(db: Session, new_alerts: list[models.ModelLifecycleAlert]) -> int:
    """Send email notifications to admin users for new lifecycle alerts."""
    if not new_alerts:
        return 0

    admin_emails_raw = str(settings.ADMIN_EMAILS or "")
    admin_emails = [e.strip() for e in admin_emails_raw.split(",") if e.strip()]
    if not admin_emails:
        logger.info("No ADMIN_EMAILS configured; skipping lifecycle alert emails.")
        return 0

    dashboard_url = os.getenv("FRONTEND_URL", "https://qiko.ai/signal").rstrip("/")
    email_svc = EmailService(db)
    sent = 0

    for alert in new_alerts:
        if alert.severity not in ("critical", "warning"):
            continue
        # Only email when one of OUR (Bedrock) models is actually affected. Lifecycle
        # noise about providers/models we don't run stays in the dashboard, off email.
        if not alert.affected_models:
            continue

        for email_addr in admin_emails:
            try:
                email_svc.queue_template_email(
                    to_email=email_addr,
                    template_key="admin.model_lifecycle_alert",
                    context={
                        "dashboard_url": dashboard_url,
                        "provider": alert.provider,
                        "severity": alert.severity,
                        "alert_type": alert.alert_type,
                        "title": alert.title,
                        "description": alert.description,
                        "affected_models": ", ".join(alert.affected_models or []),
                        "source_url": alert.source_url or "",
                        "timestamp": alert.created_at.strftime("%Y-%m-%d %H:%M UTC")
                        if alert.created_at
                        else "",
                    },
                    correlation_id=f"model_lifecycle:{alert.id}",
                )
                sent += 1
            except Exception as exc:
                logger.warning("Failed to queue lifecycle alert email to %s: %s", email_addr, exc)

    return sent


def run_model_lifecycle_check(db: Session) -> dict[str, Any]:
    """Main entry point: fetch all sources, diff, create alerts, send emails.

    Returns a summary dict for logging.
    """
    now = datetime.now(timezone.utc)
    summary: dict[str, Any] = {
        "sources_checked": 0,
        "sources_failed": 0,
        "pages_changed": 0,
        "alerts_created": 0,
        "emails_sent": 0,
    }

    all_new_alerts: list[models.ModelLifecycleAlert] = []

    for source in MONITOR_SOURCES:
        provider = source["provider"]
        url = source["url"]
        page_type = source["page_type"]

        raw_html = _fetch_page(url)
        if raw_html is None:
            summary["sources_failed"] += 1
            continue
        summary["sources_checked"] += 1

        plain_text = _strip_html(raw_html)
        content_hash = _hash_content(plain_text)

        # Get previous snapshot
        prev = _get_previous_snapshot(db, provider, url)

        # Extract model references
        model_refs = _extract_model_references(plain_text, provider)

        if prev and prev.content_hash == content_hash:
            # Page hasn't changed, skip
            continue

        summary["pages_changed"] += 1

        # Page changed: compute detailed diffs
        prev_models = prev.extracted_models if prev else None
        new_alerts_data = _build_alerts_from_diff(
            provider=provider,
            source_url=url,
            page_type=page_type,
            prev_models=prev_models,
            curr_models=model_refs,
        )

        # If page changed but no specific model-level diffs, still record an info alert
        if not new_alerts_data and prev is not None:
            new_alerts_data.append(
                {
                    "provider": provider,
                    "alert_type": "page_changed",
                    "severity": "info",
                    "title": f"{provider.title()} {page_type} page updated",
                    "description": f"The {provider} {page_type} page content changed. Review for relevant updates.",
                    "affected_models": None,
                    "details": {"previous_hash": prev.content_hash, "new_hash": content_hash},
                    "source_url": url,
                }
            )

        # Persist new snapshot
        snapshot = models.ModelLifecycleSnapshot(
            provider=provider,
            source_url=url,
            page_type=page_type,
            content_hash=content_hash,
            extracted_models=model_refs,
            raw_text_excerpt=plain_text[:2000] if plain_text else None,
            fetched_at=now,
        )
        db.add(snapshot)

        # Persist alerts
        for alert_data in new_alerts_data:
            alert = models.ModelLifecycleAlert(
                provider=alert_data["provider"],
                alert_type=alert_data["alert_type"],
                severity=alert_data["severity"],
                title=alert_data["title"],
                description=alert_data["description"],
                affected_models=alert_data.get("affected_models"),
                details=alert_data.get("details"),
                source_url=alert_data.get("source_url"),
                created_at=now,
            )
            db.add(alert)
            db.flush()  # get the id assigned
            all_new_alerts.append(alert)

        summary["alerts_created"] += len(new_alerts_data)

    # Send email alerts for critical/warning items
    emails_sent = _send_admin_email_alerts(db, all_new_alerts)
    summary["emails_sent"] = emails_sent

    return summary
