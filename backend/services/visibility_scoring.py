"""Continuous multi-factor visibility scoring.

Replaces the legacy ternary 0/50/100 system with a continuous 0-100 scale
that considers citation presence, citation position, text-mention quality,
and topic relevance.
"""

from __future__ import annotations

from typing import NamedTuple
from urllib.parse import urlparse


class ScoreResult(NamedTuple):
    """Visibility score with per-factor breakdown."""

    score: float
    breakdown: dict[str, float]


def normalize_domain(value: str | None) -> str | None:
    """Normalize a domain or URL to a bare lower-case domain without ``www.``."""
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    try:
        parsed = urlparse(normalized if "://" in normalized else f"https://{normalized}")
        candidate = (parsed.hostname or "").strip().lower().rstrip(".")
    except Exception:
        candidate = normalized.rstrip(".")
    if candidate.startswith("www."):
        candidate = candidate[4:]
    return candidate or None


def matches_target_domain(citation: str, target_domain: str | None) -> bool:
    """Return *True* when *citation* belongs to *target_domain*."""
    normalized_target = normalize_domain(target_domain)
    if not normalized_target:
        return False
    normalized_citation = normalize_domain(citation)
    if normalized_citation:
        return normalized_citation == normalized_target or normalized_citation.endswith(
            f".{normalized_target}"
        )
    return normalized_target in str(citation or "").strip().lower()


# ---------------------------------------------------------------------------
# Multi-factor scoring
# ---------------------------------------------------------------------------

_RECOMMENDATION_KEYWORDS = frozenset(
    ["recommend", "best", "top", "leading", "preferred", "suggest", "ideal", "excellent"]
)


def score_response(
    topic: str,
    text: str,
    valid_citations: list[str],
    *,
    target_domain: str | None = None,
) -> ScoreResult:
    """Score how well *text* surfaces the target in response to *topic*.

    Returns a continuous 0-100 score built from four factors:

    * **citation_presence** (0-40):  target domain cited, bonus per extra citation
    * **citation_position** (0-20):  first-position citations score higher
    * **text_mention** (0-20):  domain mentioned in body text, prominence, frequency
    * **topic_relevance** (0-20):  topic addressed, prominence, recommendation context
    """
    normalized_topic = topic.strip().lower()
    normalized_domain = normalize_domain(target_domain)
    haystack = text.lower()
    text_len = max(len(text), 1)

    # -- Factor 1: Citation presence (0-40 pts) ----------------------------
    if normalized_domain:
        target_citations = [
            c for c in valid_citations if matches_target_domain(c, normalized_domain)
        ]
    else:
        target_citations = [
            c for c in valid_citations if normalized_topic and normalized_topic in c.lower()
        ]

    if target_citations:
        citation_score = 30.0 + min(10.0, len(target_citations) * 3.0)
    else:
        citation_score = 0.0

    # -- Factor 2: Citation position (0-20 pts) ----------------------------
    position_score = 0.0
    if target_citations and valid_citations:
        for idx, c in enumerate(valid_citations):
            is_match = (
                matches_target_domain(c, normalized_domain)
                if normalized_domain
                else (normalized_topic and normalized_topic in c.lower())
            )
            if is_match:
                position_score = max(0.0, 20.0 - idx * 5.0)
                break

    # -- Factor 3: Text-mention quality (0-20 pts) -------------------------
    text_score = 0.0
    check_domain = normalized_domain or ""
    if check_domain and check_domain in haystack:
        text_score += 10.0
        first_mention = haystack.find(check_domain)
        if first_mention < text_len * 0.2:
            text_score += 5.0
        extra_mentions = haystack.count(check_domain) - 1
        text_score += min(5.0, max(0.0, extra_mentions) * 2.0)

    # -- Factor 4: Topic relevance (0-20 pts) ------------------------------
    topic_score = 0.0
    if normalized_topic and normalized_topic in haystack:
        topic_score += 10.0
        topic_pos = haystack.find(normalized_topic)
        if topic_pos < text_len * 0.3:
            topic_score += 5.0
        nearby_start = max(0, topic_pos - 100)
        nearby_end = min(len(haystack), topic_pos + len(normalized_topic) + 100)
        nearby_text = haystack[nearby_start:nearby_end]
        if any(kw in nearby_text for kw in _RECOMMENDATION_KEYWORDS):
            topic_score += 5.0

    breakdown = {
        "citation_presence": round(citation_score, 1),
        "citation_position": round(position_score, 1),
        "text_mention": round(text_score, 1),
        "topic_relevance": round(topic_score, 1),
    }
    total = min(100.0, round(citation_score + position_score + text_score + topic_score, 1))
    return ScoreResult(score=total, breakdown=breakdown)
