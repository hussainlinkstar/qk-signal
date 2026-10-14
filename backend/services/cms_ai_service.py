"""AI-assisted CMS draft generation helpers."""

from __future__ import annotations

import base64
import json
import logging
import re
import uuid
from typing import Any
from urllib.parse import quote
from core.bedrock_text import bedrock_available, bedrock_generate_text
from core.config import settings
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
_BASE64_BYTE_PATTERN = re.compile(rb"^[A-Za-z0-9+/=\s]+$")


class CmsAIGenerationError(RuntimeError):
    """Raised when AI generation fails and no safe fallback can be produced."""


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9\s-]", "", value).strip().lower()
    normalized = re.sub(r"[\s_-]+", "-", normalized)
    return normalized.strip("-") or "untitled"


def _strip_code_fences(raw_text: str) -> str:
    trimmed = raw_text.strip()
    if trimmed.startswith("```"):
        trimmed = re.sub(r"^```(?:json)?", "", trimmed).strip()
        trimmed = re.sub(r"```$", "", trimmed).strip()
    return trimmed


def _extract_json_payload(raw_text: str) -> dict[str, Any]:
    cleaned = _strip_code_fences(raw_text)
    try:
        payload = json.loads(cleaned)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        candidate = cleaned[start : end + 1]
        payload = json.loads(candidate)
        if isinstance(payload, dict):
            return payload
    raise CmsAIGenerationError("Gemini returned an invalid JSON payload.")


def _coerce_string_list(value: Any, fallback: list[str] | None = None) -> list[str]:
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        if items:
            return items
    return fallback or []


def _normalize_faq_items(value: Any, *, topic: str) -> list[dict[str, str]]:
    fallback = [
        {
            "question": f"What is the first step to improve {topic}?",
            "answer": "Start with a baseline audit and prioritize fixes by impact and implementation effort.",
        },
        {
            "question": "How do FAQ sections help GEO and AEO?",
            "answer": "They structure direct answers in a format that LLMs and answer engines can extract quickly.",
        },
        {
            "question": "How often should this strategy be reviewed?",
            "answer": "Review performance weekly and refresh priorities monthly based on score movement and citations.",
        },
    ]

    if not isinstance(value, list):
        return fallback

    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or item.get("q") or "").strip()
        answer = str(item.get("answer") or item.get("a") or "").strip()
        if not question or not answer:
            continue
        normalized.append({"question": question, "answer": answer})
        if len(normalized) >= 5:
            break
    return normalized or fallback


def _ensure_faq_section(body_markdown: str, faq_items: list[dict[str, str]]) -> str:
    if not body_markdown.strip() or not faq_items:
        return body_markdown
    if re.search(r"^\s*##+\s*faq\b", body_markdown, flags=re.IGNORECASE | re.MULTILINE):
        return body_markdown

    faq_lines: list[str] = ["", "## FAQ", ""]
    for item in faq_items:
        question = item.get("question", "").strip()
        answer = item.get("answer", "").strip()
        if not question or not answer:
            continue
        faq_lines.append(f"### {question}")
        faq_lines.append(answer)
        faq_lines.append("")
    faq_section = "\n".join(faq_lines).strip()
    return f"{body_markdown.rstrip()}\n\n{faq_section}\n"


def _normalize_markdown_body(markdown: str) -> str:
    text = (markdown or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return text

    raw_lines = [line.rstrip() for line in text.split("\n")]
    normalized_lines: list[str] = []
    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            normalized_lines.append("")
            continue

        heading_match = re.match(r"^\d+\.\s+(.+)$", stripped)
        if heading_match:
            heading = heading_match.group(1).strip().rstrip(":")
            normalized_lines.extend(["", f"## {heading}", ""])
            continue

        metric_match = re.match(r"^(Focus|Goal|KPI|KPIs)\s*:\s*(.+)$", stripped, re.IGNORECASE)
        if metric_match:
            label = metric_match.group(1).upper()
            value = metric_match.group(2).strip()
            normalized_lines.append(f"- **{label}:** {value}")
            continue

        normalized_lines.append(stripped)

    compact_lines: list[str] = []
    for line in normalized_lines:
        if line == "" and (not compact_lines or compact_lines[-1] == ""):
            continue
        compact_lines.append(line)
    result = "\n".join(compact_lines).strip()
    if not result.startswith("#"):
        result = f"## Executive Summary\n\n{result}"
    return result


def _looks_like_image_bytes(raw_data: bytes) -> bool:
    if raw_data.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if raw_data.startswith(b"\xff\xd8\xff"):
        return True
    if raw_data.startswith(b"GIF87a") or raw_data.startswith(b"GIF89a"):
        return True
    if len(raw_data) >= 12 and raw_data.startswith(b"RIFF") and raw_data[8:12] == b"WEBP":
        return True
    stripped = raw_data.lstrip()
    if stripped.startswith(b"<svg") or stripped.startswith(b"<?xml"):
        return True
    return False


def _decode_base64_bytes_if_possible(raw_data: bytes) -> bytes | None:
    compact = re.sub(rb"\s+", b"", raw_data)
    if len(compact) < 4:
        return None
    if _BASE64_BYTE_PATTERN.fullmatch(compact) is None:
        return None
    try:
        return base64.b64decode(compact, validate=True)
    except Exception:
        return None


def _normalize_binary_payload(raw_data: bytes) -> bytes:
    if _looks_like_image_bytes(raw_data):
        return raw_data

    decoded = _decode_base64_bytes_if_possible(raw_data)
    if decoded is None:
        return raw_data
    if _looks_like_image_bytes(decoded):
        return decoded

    nested_decoded = _decode_base64_bytes_if_possible(decoded)
    if nested_decoded is not None and _looks_like_image_bytes(nested_decoded):
        return nested_decoded
    return raw_data


def normalize_cms_image_data_url(image_url: str | None) -> str | None:
    if image_url is None:
        return None

    stripped = image_url.strip()
    if not stripped:
        return None
    if not stripped.lower().startswith("data:image/"):
        return stripped

    marker = ";base64,"
    marker_index = stripped.lower().find(marker)
    if marker_index < 0:
        return stripped

    header = stripped[: marker_index + len(marker)]
    payload = stripped[marker_index + len(marker) :]
    compact_payload = re.sub(r"\s+", "", payload)
    # Fast path for already valid image payloads to avoid expensive decode/encode on every request.
    if (
        compact_payload.startswith("iVBOR")
        or compact_payload.startswith("/9j/")
        or compact_payload.startswith("R0lGOD")
        or compact_payload.startswith("UklGR")
        or compact_payload.startswith("PHN2Zy")
    ):
        return f"{header}{compact_payload}"

    decoded = _decode_base64_bytes_if_possible(compact_payload.encode("utf-8", "ignore"))
    if decoded is None:
        return stripped

    nested_data_url = decoded.decode("utf-8", "ignore").strip()
    if nested_data_url.lower().startswith("data:image/"):
        return normalize_cms_image_data_url(nested_data_url) or stripped

    normalized_binary = _normalize_binary_payload(decoded)
    if not _looks_like_image_bytes(normalized_binary):
        return stripped

    mime_type = header[5:].split(";", 1)[0].strip() or "image/png"
    encoded = base64.b64encode(normalized_binary).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _detect_image_mime_and_ext(data: bytes) -> tuple[str, str]:
    """Detect MIME type and file extension from image magic bytes."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", ".png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg", ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif", ".gif"
    if data[:5] == b"<?xml" or data[:4] == b"<svg":
        return "image/svg+xml", ".svg"
    return "image/png", ".png"


def upload_cms_image_to_storage(
    data_url: str,
    *,
    slug: str = "",
    entity_type: str = "articles",
) -> str | None:
    """Decode a base64 data URL, upload to GCS/local storage, return public URL.

    Returns the public URL on success, or ``None`` if the input is not a
    data URL (e.g. already an https:// URL) or upload fails.
    """
    stripped = (data_url or "").strip()
    if not stripped.lower().startswith("data:image/"):
        return None

    marker = ";base64,"
    marker_idx = stripped.lower().find(marker)
    if marker_idx < 0:
        return None

    payload_b64 = stripped[marker_idx + len(marker) :]
    payload_b64 = re.sub(r"\s+", "", payload_b64)
    try:
        image_bytes = base64.b64decode(payload_b64, validate=True)
    except Exception:
        logger.warning("CMS image upload: failed to decode base64 payload (slug=%s)", slug)
        return None

    if len(image_bytes) < 64:
        return None

    mime_type, ext = _detect_image_mime_and_ext(image_bytes)
    slug_prefix = slugify(slug)[:60] if slug else "image"
    filename = f"{slug_prefix}-{uuid.uuid4().hex[:12]}{ext}"

    from services.s3_storage_service import get_storage_service

    gcs = get_storage_service()
    storage_uri = gcs.upload_file(
        prefix=f"{settings.STORAGE_CMS_PREFIX}{entity_type}/",
        filename=filename,
        data=image_bytes,
        content_type=mime_type,
        cache_control="public,max-age=31536000",
    )

    if storage_uri.startswith("s3://"):
        # Private bucket -> serve through the backend proxy (backend has IAM read access).
        key = storage_uri.split("/", 3)[3] if storage_uri.count("/") >= 3 else ""
        backend_base = (settings.BACKEND_PUBLIC_URL or "http://localhost:8000").rstrip("/")
        public_url = f"{backend_base}/api/v1/uploads/cms/s3/{quote(key, safe=chr(47))}"
        logger.info("CMS image uploaded to S3 (served via backend): %s -> %s", slug, public_url)
        return public_url

    public_url = gcs.to_public_url(storage_uri)
    if public_url:
        logger.info("CMS image uploaded: %s -> %s", slug, public_url)
        return public_url

    if storage_uri.startswith("local://"):
        object_path = storage_uri[8:]
        backend_base = (settings.BACKEND_PUBLIC_URL or "http://localhost:8000").rstrip("/")
        local_url = (
            f"{backend_base}/api/v1/uploads/cms/local/{quote(object_path.strip('/'), safe='/')}"
        )
        logger.info("CMS image uploaded to local storage: %s -> %s", slug, local_url)
        return local_url

    return None


def _openai_generate_text(prompt: str) -> str | None:
    """Generate text (JSON) via AWS Bedrock. Returns content or None.

    Bedrock-only inference: this routes the CMS text-generation prompt through the
    shared ``bedrock_generate_text`` helper (smart tier). The caller-supplied prompt
    already embeds the required JSON schema, and the system message instructs the
    model to emit strict JSON, which the call sites parse with ``_extract_json_payload``.
    """
    if not bedrock_available():
        return None
    try:
        return bedrock_generate_text(
            "You are a senior content strategist for a technical SaaS. "
            "Output strict, valid JSON only — no markdown fences, no commentary.",
            prompt,
            tier="smart",
            max_tokens=4096,
            use_case="cms_text",
        )
    except Exception as exc:
        logger.warning("CMS text generation (Bedrock) failed: %s", exc)
        return None


def _build_fallback_article(
    topic: str, audience: str, tone: str, keywords: list[str]
) -> dict[str, Any]:
    title = f"{topic.strip().title()} for {audience.strip().title()}"
    tags = keywords[:6] if keywords else ["SEO", "AEO", "GEO", "AI Search"]
    excerpt = (
        f"A practical guide on {topic.strip()} tailored for {audience.strip()} teams, "
        "covering measurable wins across SEO, AEO, and GEO."
    )
    body = "\n".join(
        [
            f"# {title}",
            "",
            "## Why this matters now",
            (
                f"AI-native search experiences are shifting discovery behaviors. "
                f"This brief explains how {topic.strip()} influences visibility, citations, and trust."
            ),
            "",
            "## Strategic actions",
            "- Strengthen schema markup coverage on critical landing pages.",
            "- Publish semantic clusters aligned to intent and entity salience.",
            "- Improve citation readiness with source-backed, concise answers.",
            "",
            "## 30-day execution plan",
            "1. Run baseline audits for top transactional and informational pages.",
            "2. Prioritize recommendations by impact-to-effort score.",
            "3. Re-audit weekly and track movement in GEO/AEO/SEO scorecards.",
            "",
            "## Operational KPI checklist",
            "- Structured data completeness",
            "- Answer citation share",
            "- Content freshness velocity",
            "- AI summary inclusion rate",
            "",
            f"_Draft style: {tone.strip()}_",
        ]
    )
    faq_items = _normalize_faq_items([], topic=topic.strip())
    body = _ensure_faq_section(body, faq_items)
    return {
        "title": title,
        "slug": slugify(title),
        "excerpt": excerpt,
        "body_markdown": body,
        "seo_title": f"{title} | Qiko Signal",
        "seo_description": excerpt,
        # Featured images are uploaded manually by an editor; AI/auto image
        # generation has been removed. Default to empty (no image) here.
        "featured_image_url": "",
        "featured_image_alt": f"Editorial hero illustration for {title}",
        "tags": tags,
        "category": "Strategy",
        "author_name": "Qiko Signal Research",
        "reading_time_minutes": 8,
        "faq_items": faq_items,
        "source": "fallback",
    }


def generate_article_draft(
    *,
    topic: str,
    target_audience: str,
    tone: str,
    keywords: list[str],
    category: str | None = None,
) -> dict[str, Any]:
    safe_topic = topic.strip()
    safe_audience = target_audience.strip() or "marketing"
    safe_tone = tone.strip() or "professional"
    safe_keywords = [item.strip() for item in keywords if item and item.strip()]

    if not safe_topic:
        raise CmsAIGenerationError("topic is required for article generation.")

    if not bedrock_available():
        # Featured image is a manual upload; the fallback draft ships without one.
        return _build_fallback_article(safe_topic, safe_audience, safe_tone, safe_keywords)

    keyword_line = ", ".join(safe_keywords[:8]) if safe_keywords else "seo, aeo, geo, llm search"
    category_hint = category.strip() if category and category.strip() else "Insights"

    prompt = (
        "You are a senior content strategist for a technical SaaS.\n"
        "Generate a publication-ready JSON object for a CMS article.\n"
        "Return valid JSON only (no markdown fences).\n\n"
        f"Topic: {safe_topic}\n"
        f"Target audience: {safe_audience}\n"
        f"Tone: {safe_tone}\n"
        f"Keywords: {keyword_line}\n"
        f"Category: {category_hint}\n\n"
        "Content formatting requirements for body_markdown:\n"
        "- Use markdown headings (## and ###), not numbered pseudo-headings.\n"
        "- Keep paragraphs concise (2-4 lines).\n"
        "- Use bullet lists for tactical steps and checklists.\n"
        "- Avoid HTML, avoid markdown code fences, avoid giant unbroken blocks.\n\n"
        "FAQ requirements:\n"
        "- Include a short FAQ with 3 to 5 practical Q&A pairs focused on high-intent user questions.\n"
        "- Keep each answer concise and specific (1-3 sentences).\n\n"
        "Required JSON schema:\n"
        "{\n"
        '  "title": "string",\n'
        '  "slug": "string",\n'
        '  "excerpt": "string",\n'
        '  "body_markdown": "string (markdown, at least 6 sections, practical and data-driven)",\n'
        '  "seo_title": "string <= 60 chars",\n'
        '  "seo_description": "string <= 155 chars",\n'
        '  "featured_image_alt": "string",\n'
        '  "tags": ["string", "string"],\n'
        '  "faq_items": [{"question": "string", "answer": "string"}],\n'
        '  "category": "string",\n'
        '  "author_name": "string",\n'
        '  "reading_time_minutes": 8\n'
        "}"
    )

    raw_text = (_openai_generate_text(prompt) or "").strip()
    payload = _extract_json_payload(raw_text)

    title = str(payload.get("title") or safe_topic.title()).strip()
    excerpt = str(payload.get("excerpt") or "").strip()
    body_markdown = _normalize_markdown_body(str(payload.get("body_markdown") or ""))
    if not excerpt or not body_markdown:
        raise CmsAIGenerationError("Gemini returned an incomplete article draft.")
    faq_items = _normalize_faq_items(payload.get("faq_items"), topic=safe_topic)
    body_markdown = _ensure_faq_section(body_markdown, faq_items)

    resolved_slug = slugify(str(payload.get("slug") or title))
    featured_image_alt = str(
        payload.get("featured_image_alt") or f"Featured visual for {title}"
    ).strip()

    return {
        "title": title,
        "slug": resolved_slug,
        "excerpt": excerpt,
        "body_markdown": body_markdown,
        "seo_title": str(payload.get("seo_title") or f"{title} | Qiko Signal").strip(),
        "seo_description": str(payload.get("seo_description") or excerpt[:155]).strip(),
        # Featured images are uploaded manually by an editor; AI/auto image
        # generation has been removed. Default to empty (no image).
        "featured_image_url": "",
        "featured_image_alt": featured_image_alt,
        "tags": _coerce_string_list(payload.get("tags"), fallback=safe_keywords[:6]),
        "category": str(payload.get("category") or category_hint).strip(),
        "author_name": str(payload.get("author_name") or "Qiko Signal Research").strip(),
        "reading_time_minutes": int(payload.get("reading_time_minutes") or 8),
        "faq_items": faq_items,
        "source": "bedrock",
    }


# ---------------------------------------------------------------------------
# Case Study Generation from Project Audit History (AEX-36)
# ---------------------------------------------------------------------------

_PII_EMAIL_RE = re.compile(r"\S+@\S+\.\S+")
_PII_PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}\b")


def _round_to_nearest(value: float | None, nearest: int = 5) -> float | None:
    if value is None:
        return None
    return round(round(float(value) / nearest) * nearest, 1)


def _relative_period_label(days: int | None) -> str:
    if days is None:
        return "over several months"
    if days <= 14:
        return "within two weeks"
    if days <= 30:
        return "over approximately one month"
    if days <= 60:
        return "over approximately two months"
    if days <= 90:
        return "over approximately three months"
    if days <= 180:
        return "over approximately six months"
    return "over approximately one year"


def _anonymize_context(
    context: dict[str, Any],
    *,
    project_name: str,
    domain_url: str | None,
    competitor_names: list[str] | None = None,
) -> dict[str, Any]:
    """Strip PII and identifying information from context payload for GDPR compliance."""
    raw = json.dumps(context, default=str)

    if project_name and project_name.strip():
        raw = raw.replace(project_name, context.get("industry_descriptor", "an enterprise client"))

    if domain_url:
        domain_clean = domain_url.strip().rstrip("/")
        for variant in [
            domain_clean,
            domain_clean.replace("https://", "").replace("http://", ""),
            domain_clean.replace("https://www.", "").replace("http://www.", ""),
        ]:
            if variant:
                raw = raw.replace(variant, "[client-domain.example]")

    for idx, comp in enumerate(competitor_names or []):
        if comp and comp.strip():
            raw = raw.replace(comp, f"Competitor {chr(65 + idx)}")

    raw = _PII_EMAIL_RE.sub("[email-redacted]", raw)
    raw = _PII_PHONE_RE.sub("[phone-redacted]", raw)

    return json.loads(raw)


def _scan_pii(text: str, *, project_name: str | None, domain_url: str | None) -> list[str]:
    """Post-generation PII scanner. Returns list of warning strings."""
    warnings_list: list[str] = []
    if _PII_EMAIL_RE.search(text):
        warnings_list.append("Potential email address detected in generated content.")
    if _PII_PHONE_RE.search(text):
        warnings_list.append("Potential phone number detected in generated content.")
    if project_name and project_name.strip() and project_name.strip().lower() in text.lower():
        warnings_list.append(f"Source project name '{project_name}' detected in generated content.")
    if domain_url:
        domain_clean = (
            domain_url.strip()
            .rstrip("/")
            .replace("https://", "")
            .replace("http://", "")
            .replace("www.", "")
        )
        if domain_clean and domain_clean.lower() in text.lower():
            warnings_list.append(f"Source domain '{domain_clean}' detected in generated content.")
    return warnings_list


def _assemble_case_study_context(
    db: Session,
    *,
    project: Any,
    anonymize: bool,
    anonymize_url: bool,
    include_competitors: bool,
    include_raw_scores: bool,
) -> dict[str, Any]:
    """Assemble context payload from project audit history for case study generation.

    Follows GDPR data minimization: only score deltas and summaries, not full audit payloads.
    """
    import models
    from services.project_audit_scope import own_project_audit_clause
    from services.project_progress_service import build_project_period_comparison

    context: dict[str, Any] = {}

    # -- Industry descriptor for anonymization --
    industry = (
        project.industry if hasattr(project, "industry") and project.industry else "technology"
    )
    context["industry_descriptor"] = f"a leading {industry} company"
    context["industry"] = industry

    # -- 1. Audit count & date range --
    audits = (
        db.query(models.Audit)
        .filter(models.Audit.project_id == project.id, own_project_audit_clause())
        .order_by(models.Audit.created_at.asc())
        .all()
    )
    context["audit_count"] = len(audits)
    if not audits:
        return context

    first_audit = audits[0]
    latest_audit = audits[-1]
    first_date = first_audit.created_at
    latest_date = latest_audit.created_at
    if first_date and latest_date:
        days_span = (latest_date - first_date).days
        context["date_range_days"] = days_span
        if anonymize:
            context["date_range_label"] = _relative_period_label(days_span)
        else:
            context["date_range"] = {
                "first_audit": first_date.isoformat(),
                "latest_audit": latest_date.isoformat(),
            }

    # -- 2. Score progression (first vs latest) --
    def _score(audit: Any, field: str) -> float | None:
        val = getattr(audit, field, None)
        if val is None:
            return None
        return float(val)

    first_scores = {
        "seo": _score(first_audit, "seo_score"),
        "geo": _score(first_audit, "geo_score"),
        "aeo": _score(first_audit, "aeo_score"),
    }
    latest_scores = {
        "seo": _score(latest_audit, "seo_score"),
        "geo": _score(latest_audit, "geo_score"),
        "aeo": _score(latest_audit, "aeo_score"),
    }

    if anonymize:
        first_scores = {k: _round_to_nearest(v) for k, v in first_scores.items()}
        latest_scores = {k: _round_to_nearest(v) for k, v in latest_scores.items()}

    deltas = {}
    for key in ["seo", "geo", "aeo"]:
        if first_scores.get(key) is not None and latest_scores.get(key) is not None:
            delta = latest_scores[key] - first_scores[key]
            deltas[key] = _round_to_nearest(delta) if anonymize else round(delta, 1)

    context["score_progression"] = {
        "initial": first_scores,
        "current": latest_scores,
        "deltas": deltas,
    }

    # -- 3. Period comparison (30d) --
    try:
        comparison = build_project_period_comparison(db, project_id=project.id, period="30d")
        if anonymize:
            for period_key in ["current_period", "previous_period"]:
                period_data = comparison.get(period_key, {})
                for score_key in ["seo", "geo", "aeo", "overall"]:
                    if score_key in period_data and period_data[score_key] is not None:
                        period_data[score_key] = _round_to_nearest(period_data[score_key])
            for score_key in ["seo", "geo", "aeo", "overall"]:
                if comparison.get("delta", {}).get(score_key) is not None:
                    comparison["delta"][score_key] = _round_to_nearest(
                        comparison["delta"][score_key]
                    )
        context["period_comparison"] = {
            "current_scores": comparison.get("current_period", {}),
            "previous_scores": comparison.get("previous_period", {}),
            "delta": comparison.get("delta", {}),
            "trend_direction": comparison.get("trend_direction", {}),
        }
    except (ValueError, Exception) as exc:
        logger.debug("Period comparison unavailable for project %s: %s", project.id, exc)

    # -- 4. Remediation outcomes --
    remediation_rows = (
        db.query(models.SignalRemediationOutcome)
        .filter(models.SignalRemediationOutcome.project_id == project.id)
        .order_by(models.SignalRemediationOutcome.completed_at.desc().nullslast())
        .limit(10)
        .all()
    )
    remediation_summaries = []
    for row in remediation_rows:
        entry: dict[str, Any] = {"category": row.recommendation_category}
        if include_raw_scores:
            if anonymize:
                entry["before_geo"] = _round_to_nearest(row.before_score_geo)
                entry["after_geo"] = _round_to_nearest(row.after_score_geo)
                entry["before_aeo"] = _round_to_nearest(row.before_score_aeo)
                entry["after_aeo"] = _round_to_nearest(row.after_score_aeo)
            else:
                entry["before_geo"] = row.before_score_geo
                entry["after_geo"] = row.after_score_geo
                entry["before_aeo"] = row.before_score_aeo
                entry["after_aeo"] = row.after_score_aeo
            entry["delta_geo"] = (
                _round_to_nearest(row.score_delta_geo) if anonymize else row.score_delta_geo
            )
            entry["delta_aeo"] = (
                _round_to_nearest(row.score_delta_aeo) if anonymize else row.score_delta_aeo
            )
        if row.days_to_impact is not None:
            entry["days_to_impact"] = row.days_to_impact
        remediation_summaries.append(entry)
    if remediation_summaries:
        context["remediation_outcomes"] = remediation_summaries
        context["remediation_count"] = len(remediation_rows)

    # -- 5. Entity authority snapshots --
    try:
        ea_snapshots = (
            db.query(models.EntityAuthoritySnapshot)
            .filter(models.EntityAuthoritySnapshot.project_id == project.id)
            .order_by(models.EntityAuthoritySnapshot.computed_at.desc())
            .limit(5)
            .all()
        )
        if ea_snapshots:
            ea_summaries = []
            for snap in ea_snapshots:
                ea_entry: dict[str, Any] = {
                    "authority_score": _round_to_nearest(snap.authority_score)
                    if anonymize
                    else snap.authority_score,
                }
                if hasattr(snap, "coverage_score") and snap.coverage_score is not None:
                    ea_entry["coverage"] = (
                        _round_to_nearest(snap.coverage_score) if anonymize else snap.coverage_score
                    )
                if hasattr(snap, "depth_score") and snap.depth_score is not None:
                    ea_entry["depth"] = (
                        _round_to_nearest(snap.depth_score) if anonymize else snap.depth_score
                    )
                ea_summaries.append(ea_entry)
            context["entity_authority_trend"] = ea_summaries
    except Exception as exc:
        logger.debug("Entity authority unavailable for project %s: %s", project.id, exc)

    # -- 6. Progress report highlights --
    try:
        latest_report = (
            db.query(models.ProjectProgressReport)
            .filter(models.ProjectProgressReport.project_id == project.id)
            .order_by(models.ProjectProgressReport.report_month.desc())
            .first()
        )
        if latest_report and isinstance(latest_report.snapshot_json, dict):
            snapshot = latest_report.snapshot_json
            context["progress_highlights"] = snapshot.get("highlights", [])
            context["remaining_issues"] = snapshot.get("remaining_issues", [])
    except Exception as exc:
        logger.debug("Progress report unavailable for project %s: %s", project.id, exc)

    # -- 7. Competitor data (opt-in) --
    if include_competitors:
        try:
            competitor_rows = (
                db.query(models.ProjectCompetitorSnapshot, models.ProjectCompetitor.display_name)
                .join(
                    models.ProjectCompetitor,
                    models.ProjectCompetitorSnapshot.competitor_id == models.ProjectCompetitor.id,
                )
                .filter(models.ProjectCompetitorSnapshot.project_id == project.id)
                .order_by(models.ProjectCompetitorSnapshot.created_at.desc())
                .limit(10)
                .all()
            )
            comp_names: list[str] = []
            comp_summaries: list[dict[str, Any]] = []
            for snap, display_name in competitor_rows:
                name = display_name or "Unknown"
                if name not in comp_names:
                    comp_names.append(name)
                comp_entry: dict[str, Any] = {}
                if anonymize:
                    comp_entry["name"] = f"Competitor {chr(65 + comp_names.index(name))}"
                else:
                    comp_entry["name"] = name
                for field in ["seo_score", "geo_score", "aeo_score"]:
                    val = getattr(snap, field, None)
                    if val is not None:
                        comp_entry[field.replace("_score", "")] = (
                            _round_to_nearest(float(val)) if anonymize else float(val)
                        )
                comp_summaries.append(comp_entry)
            if comp_summaries:
                context["competitor_positioning"] = comp_summaries[:6]
                context["_competitor_names"] = comp_names
        except Exception as exc:
            logger.debug("Competitor data unavailable for project %s: %s", project.id, exc)

    return context


def _build_case_study_prompt(
    context: dict[str, Any],
    *,
    anonymize: bool,
    tone: str,
) -> str:
    context_json = json.dumps(
        {k: v for k, v in context.items() if not k.startswith("_")},
        indent=2,
        default=str,
    )
    privacy_line = (
        "Client is fully anonymized. Use the industry descriptor, never invent a company name."
        if anonymize
        else f"Client: {context.get('industry_descriptor', 'an enterprise client')}"
    )

    return (
        "You are a senior marketing content strategist for Qiko Signal, an enterprise "
        "SEO/GEO/AEO audit platform. Generate a compelling, data-driven case study "
        "from the following measured project audit data.\n\n"
        f"TONE: {tone}\n"
        f"PRIVACY: {privacy_line}\n\n"
        "IMPORTANT RULES:\n"
        "- Every claim must be backed by a number from the PROJECT DATA below.\n"
        "- Do NOT invent metrics or percentages not present in the data.\n"
        "- Use markdown formatting (## headings, bullet lists, bold for key metrics).\n"
        "- The challenge section should describe the initial state and problems found.\n"
        "- The solution section should describe the Qiko Signal-driven remediation approach.\n"
        "- The results section must include a before/after comparison with real deltas.\n"
        "- metrics_json should contain 3-6 key metric highlights as {label, value} pairs.\n\n"
        f"PROJECT DATA:\n{context_json}\n\n"
        "Return a pure JSON object (no markdown fences) with these fields:\n"
        "{\n"
        '  "title": "Compelling headline with a key metric",\n'
        '  "slug": "url-friendly-slug",\n'
        '  "summary": "One-paragraph hook with key metrics (2-3 sentences)",\n'
        '  "industry": "Industry vertical",\n'
        '  "client_name": "Anonymized descriptor or real name per PRIVACY rule",\n'
        '  "challenge_markdown": "## The Challenge\\n\\nMarkdown with initial findings, scores, problems",\n'
        '  "solution_markdown": "## The Solution\\n\\nMarkdown with Qiko Signal approach, phases, recommendations",\n'
        '  "results_markdown": "## The Results\\n\\nMarkdown with before/after table, timeline, wins",\n'
        '  "metrics_json": [{"label": "string", "value": "string"}],\n'
        '  "seo_title": "string <= 60 chars",\n'
        '  "seo_description": "string 150-160 chars"\n'
        "}"
    )


def _build_fallback_case_study(context: dict[str, Any], *, anonymize: bool) -> dict[str, Any]:
    """Minimal case study fallback when Gemini is unavailable."""
    industry = context.get("industry", "technology")
    client_name = context.get("industry_descriptor", f"a leading {industry} company")
    audit_count = context.get("audit_count", 0)
    scores = context.get("score_progression", {})
    initial = scores.get("initial", {})
    deltas = scores.get("deltas", {})

    title = f"How {client_name.title()} Improved AI Visibility with Qiko Signal"
    summary = (
        f"Through {audit_count} systematic audits, this {industry} organization "
        f"achieved measurable improvements across SEO, GEO, and AEO dimensions."
    )

    challenge_lines = [
        "## The Challenge",
        "",
        "Initial audit scores revealed room for improvement:",
    ]
    for key in ["seo", "geo", "aeo"]:
        val = initial.get(key)
        if val is not None:
            challenge_lines.append(f"- **{key.upper()}**: {val}")
    challenge_md = "\n".join(challenge_lines)

    solution_md = (
        "## The Solution\n\n"
        "Qiko Signal's AI-powered audit pipeline identified priority remediation areas "
        "and tracked implementation through the task lifecycle. The team focused on:\n\n"
        "- Structured data optimization and schema markup coverage\n"
        "- Content restructuring for AI citation readiness\n"
        "- Entity authority strengthening through semantic gap analysis"
    )

    results_lines = ["## The Results", "", "After implementing Qiko Signal's recommendations:"]
    for key in ["seo", "geo", "aeo"]:
        delta = deltas.get(key)
        if delta is not None:
            direction = "improved" if delta > 0 else "changed"
            results_lines.append(f"- **{key.upper()}**: {direction} by {abs(delta)} points")
    results_md = "\n".join(results_lines)

    metrics = []
    for key in ["seo", "geo", "aeo"]:
        delta = deltas.get(key)
        if delta is not None:
            metrics.append(
                {
                    "label": f"{key.upper()} Improvement",
                    "value": f"+{delta}" if delta > 0 else str(delta),
                }
            )
    metrics.append({"label": "Audits Conducted", "value": str(audit_count)})

    return {
        "title": title,
        "slug": slugify(title),
        "summary": summary,
        "industry": industry,
        "client_name": client_name if anonymize else None,
        "challenge_markdown": challenge_md,
        "solution_markdown": solution_md,
        "results_markdown": results_md,
        "metrics_json": metrics,
        "seo_title": f"{title} | Qiko Signal"[:60],
        "seo_description": summary[:160],
        "source": "fallback",
        "anonymization_level": "full" if anonymize else "none",
        "pii_warnings": [],
    }


def suggest_article_topics(
    *,
    existing_titles: list[str] | None = None,
    focus_area: str | None = None,
    count: int = 4,
) -> list[dict[str, Any]]:
    """Return a list of article topic suggestions with audience, tone, and keywords.

    Each suggestion is a dict with keys: topic, target_audience, tone, keywords, category.
    Falls back to a curated static list when Bedrock is unavailable.
    """
    capped_count = max(1, min(count, 8))

    if not bedrock_available():
        return _build_fallback_topic_suggestions(capped_count, focus_area)

    existing_hint = ""
    if existing_titles:
        titles_str = "; ".join(existing_titles[:20])
        existing_hint = f"\nAlready published titles (avoid repeating these): {titles_str}\n"

    focus_hint = ""
    if focus_area and focus_area.strip():
        focus_hint = f"\nFocus area requested by the editor: {focus_area.strip()}\n"

    prompt = (
        "You are a senior content strategist for Qiko Signal, a technical SaaS platform "
        "specialising in SEO, AEO (Answer Engine Optimisation), and GEO (Generative Engine Optimisation) audits.\n\n"
        f"Generate exactly {capped_count} distinct article topic suggestions.\n"
        f"{existing_hint}{focus_hint}\n"
        "Each suggestion must include:\n"
        "- topic: a specific, compelling article title idea\n"
        "- target_audience: who the article is for (be specific, e.g. 'technical SEO leads at enterprise SaaS companies')\n"
        "- tone: the recommended writing tone (e.g. 'data-driven and authoritative')\n"
        "- keywords: array of 4-6 high-intent keywords\n"
        "- category: one of Insights, Guides, Research, Industry News\n\n"
        "Return valid JSON only (no markdown fences). The root must be an array of objects.\n"
        "Example:\n"
        '[{"topic":"...","target_audience":"...","tone":"...","keywords":["k1","k2"],"category":"Guides"}]\n'
    )

    try:
        raw_text = _openai_generate_text(prompt) or ""
        cleaned = _strip_code_fences(raw_text)

        parsed: Any = None
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("[")
            end = cleaned.rfind("]")
            if start >= 0 and end > start:
                parsed = json.loads(cleaned[start : end + 1])

        if isinstance(parsed, list):
            suggestions: list[dict[str, Any]] = []
            for item in parsed[:capped_count]:
                if not isinstance(item, dict) or "topic" not in item:
                    continue
                suggestions.append(
                    {
                        "topic": str(item.get("topic", "")).strip(),
                        "target_audience": str(
                            item.get("target_audience", "marketing leaders")
                        ).strip(),
                        "tone": str(item.get("tone", "professional")).strip(),
                        "keywords": _coerce_string_list(
                            item.get("keywords"), ["SEO", "AEO", "GEO"]
                        ),
                        "category": str(item.get("category", "Insights")).strip(),
                    }
                )
            if suggestions:
                return suggestions

        logger.warning("Bedrock returned unexpected format for topic suggestions, using fallback.")
        return _build_fallback_topic_suggestions(capped_count, focus_area)

    except Exception:
        logger.exception("Bedrock topic suggestion call failed, using fallback.")
        return _build_fallback_topic_suggestions(capped_count, focus_area)


def _build_fallback_topic_suggestions(
    count: int, focus_area: str | None = None
) -> list[dict[str, Any]]:
    """Curated static suggestions when Gemini is not available."""
    pool: list[dict[str, Any]] = [
        {
            "topic": "How AI Overviews Are Reshaping Organic Click-Through Rates in 2026",
            "target_audience": "SEO managers and growth leads at mid-market companies",
            "tone": "data-driven and analytical",
            "keywords": [
                "AI overviews",
                "CTR impact",
                "organic traffic",
                "SERP features",
                "zero-click search",
            ],
            "category": "Research",
        },
        {
            "topic": "The Complete Guide to Answer Engine Optimisation for B2B SaaS",
            "target_audience": "content strategists and technical SEO leads at B2B SaaS companies",
            "tone": "practical and step-by-step",
            "keywords": [
                "AEO",
                "answer engine",
                "B2B SaaS",
                "featured snippets",
                "conversational search",
            ],
            "category": "Guides",
        },
        {
            "topic": "Schema Markup Strategies That Improve AI Citation Rates",
            "target_audience": "technical SEO engineers and developers",
            "tone": "technical and implementation-focused",
            "keywords": [
                "schema markup",
                "structured data",
                "AI citations",
                "JSON-LD",
                "entity optimisation",
            ],
            "category": "Guides",
        },
        {
            "topic": "Measuring GEO ROI: Metrics That Matter for Generative Search Visibility",
            "target_audience": "CMOs and VP marketing at enterprise organisations",
            "tone": "strategic and executive-friendly",
            "keywords": [
                "GEO",
                "generative search",
                "ROI measurement",
                "AI visibility",
                "brand mentions",
            ],
            "category": "Insights",
        },
        {
            "topic": "Entity Authority Building: From Knowledge Graphs to LLM Training Data",
            "target_audience": "digital PR specialists and SEO strategists",
            "tone": "forward-looking and authoritative",
            "keywords": [
                "entity authority",
                "knowledge graph",
                "LLM training",
                "brand entities",
                "E-E-A-T",
            ],
            "category": "Research",
        },
        {
            "topic": "AI Crawler Bot Detection: What Your Server Logs Reveal About LLM Indexing",
            "target_audience": "webmasters and DevOps engineers managing high-traffic sites",
            "tone": "technical and investigative",
            "keywords": [
                "AI crawlers",
                "bot detection",
                "server logs",
                "GPTBot",
                "ClaudeBot",
                "robots.txt",
            ],
            "category": "Insights",
        },
        {
            "topic": "Multi-Provider AI Audit Pipelines: Why Consensus Beats Single-Model Analysis",
            "target_audience": "agency owners and SEO consultants",
            "tone": "persuasive and evidence-based",
            "keywords": [
                "multi-model audit",
                "AI consensus",
                "audit accuracy",
                "provider comparison",
            ],
            "category": "Research",
        },
        {
            "topic": "Content Brief to Published Page: An AI-Assisted Editorial Workflow",
            "target_audience": "content teams and editorial managers",
            "tone": "practical and workflow-oriented",
            "keywords": [
                "content briefs",
                "AI writing",
                "editorial workflow",
                "content operations",
            ],
            "category": "Guides",
        },
    ]
    return pool[:count]


def generate_case_study_draft_from_project(
    db: Session,
    *,
    project_id: int,
    anonymize: bool = True,
    anonymize_url: bool = True,
    include_competitors: bool = False,
    include_raw_scores: bool = True,
    tone: str = "professional",
) -> dict[str, Any]:
    """Generate a case study draft from a project's audit history using AI.

    Phase 1: anonymize=True is enforced. Non-anonymized path returns an error
    until consent infrastructure is built.
    """
    import models
    from services.project_audit_scope import own_project_audit_clause

    # Phase 1 enforcement: only anonymized case studies allowed
    if not anonymize:
        raise CmsAIGenerationError(
            "Named case studies require workspace consent infrastructure. "
            "Set anonymize=true or wait for Phase 2 consent features."
        )

    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if project is None:
        raise CmsAIGenerationError("Project not found.")

    audit_count = (
        db.query(models.Audit)
        .filter(models.Audit.project_id == project_id, own_project_audit_clause())
        .count()
    )
    if audit_count == 0:
        raise CmsAIGenerationError(
            "Project has no audit history. Run at least one audit before generating a case study."
        )

    # Assemble context from all data sources
    context = _assemble_case_study_context(
        db,
        project=project,
        anonymize=anonymize,
        anonymize_url=anonymize_url,
        include_competitors=include_competitors,
        include_raw_scores=include_raw_scores,
    )

    # Apply full anonymization pass on the assembled context
    project_name = project.name or ""
    domain_url = project.domain_url or ""
    competitor_names = context.pop("_competitor_names", [])
    if anonymize:
        context = _anonymize_context(
            context,
            project_name=project_name,
            domain_url=domain_url if anonymize_url else None,
            competitor_names=competitor_names if include_competitors else None,
        )

    # Try Bedrock generation
    if not bedrock_available():
        logger.info("Bedrock unavailable for case study generation; using fallback.")
        return _build_fallback_case_study(context, anonymize=anonymize)

    prompt = _build_case_study_prompt(context, anonymize=anonymize, tone=tone)

    try:
        raw_text = (
            bedrock_generate_text(
                "You are an expert B2B case-study writer. " "Output strict JSON only, no markdown.",
                prompt,
                tier="smart",
                max_tokens=4096,
                use_case="cms_case_study",
            )
            or ""
        ).strip()
        payload = _extract_json_payload(raw_text)
    except Exception as exc:
        logger.warning("Bedrock case study generation failed: %s, using fallback.", exc)
        return _build_fallback_case_study(context, anonymize=anonymize)

    # Parse and validate the AI response
    title = str(payload.get("title") or "Untitled Case Study").strip()
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        raise CmsAIGenerationError("Bedrock returned an incomplete case study draft.")

    challenge_md = _normalize_markdown_body(str(payload.get("challenge_markdown") or ""))
    solution_md = _normalize_markdown_body(str(payload.get("solution_markdown") or ""))
    results_md = _normalize_markdown_body(str(payload.get("results_markdown") or ""))

    metrics_raw = payload.get("metrics_json") or payload.get("metrics") or []
    metrics: list[dict[str, str]] = []
    if isinstance(metrics_raw, list):
        for item in metrics_raw[:8]:
            if isinstance(item, dict):
                label = str(item.get("label", "")).strip()
                value = str(item.get("value", "")).strip()
                if label and value:
                    metrics.append({"label": label, "value": value})

    result = {
        "title": title,
        "slug": slugify(str(payload.get("slug") or title)),
        "summary": summary,
        "industry": str(payload.get("industry") or context.get("industry", "")).strip() or None,
        "client_name": str(
            payload.get("client_name") or context.get("industry_descriptor", "")
        ).strip()
        or None,
        "challenge_markdown": challenge_md,
        "solution_markdown": solution_md,
        "results_markdown": results_md,
        "metrics_json": metrics,
        "seo_title": str(payload.get("seo_title") or f"{title} | Qiko Signal").strip()[:60],
        "seo_description": str(payload.get("seo_description") or summary[:160]).strip(),
        "source": "bedrock",
        "anonymization_level": "full" if anonymize else "none",
    }

    # Post-generation PII scan
    all_text = " ".join(str(v) for v in result.values() if isinstance(v, str))
    pii_warnings = _scan_pii(
        all_text,
        project_name=project_name,
        domain_url=domain_url,
    )
    result["pii_warnings"] = pii_warnings

    return result
