from __future__ import annotations
import re
from collections.abc import Iterable
from typing import Any

QUERY_TYPE_INFORMATIONAL = "informational"
QUERY_TYPE_DECISION_MAKING = "decision_making"

QUERY_TYPE_VALUES = {QUERY_TYPE_INFORMATIONAL, QUERY_TYPE_DECISION_MAKING}
INTENT_VALUES = {"informational", "transactional", "navigational"}
INTENT_TO_QUERY_TYPE = {
    "informational": QUERY_TYPE_INFORMATIONAL,
    "transactional": QUERY_TYPE_DECISION_MAKING,
    "navigational": QUERY_TYPE_DECISION_MAKING,
}

QUERY_CATEGORY_INSTRUCTIONAL = "instructional"
QUERY_CATEGORY_CAUSAL = "causal"
QUERY_CATEGORY_COMMERCIAL_PRICING = "commercial_pricing"
QUERY_CATEGORY_COMMERCIAL_COMPARISON = "commercial_comparison"
QUERY_CATEGORY_OTHER = "other"

QUERY_CATEGORY_VALUES = {
    QUERY_CATEGORY_INSTRUCTIONAL,
    QUERY_CATEGORY_CAUSAL,
    QUERY_CATEGORY_COMMERCIAL_PRICING,
    QUERY_CATEGORY_COMMERCIAL_COMPARISON,
    QUERY_CATEGORY_OTHER,
}

QUERY_CATEGORY_ALIASES = {
    "how_to": QUERY_CATEGORY_INSTRUCTIONAL,
    "how-to": QUERY_CATEGORY_INSTRUCTIONAL,
    "instruction": QUERY_CATEGORY_INSTRUCTIONAL,
    "instructions": QUERY_CATEGORY_INSTRUCTIONAL,
    "why": QUERY_CATEGORY_CAUSAL,
    "cause": QUERY_CATEGORY_CAUSAL,
    "causes": QUERY_CATEGORY_CAUSAL,
    "causal_reasoning": QUERY_CATEGORY_CAUSAL,
    "pricing": QUERY_CATEGORY_COMMERCIAL_PRICING,
    "price": QUERY_CATEGORY_COMMERCIAL_PRICING,
    "cost": QUERY_CATEGORY_COMMERCIAL_PRICING,
    "commercial": QUERY_CATEGORY_COMMERCIAL_PRICING,
    "comparison": QUERY_CATEGORY_COMMERCIAL_COMPARISON,
    "compare": QUERY_CATEGORY_COMMERCIAL_COMPARISON,
    "vs": QUERY_CATEGORY_COMMERCIAL_COMPARISON,
    "versus": QUERY_CATEGORY_COMMERCIAL_COMPARISON,
}

_INSTRUCTIONAL_PATTERNS = (
    re.compile(r"\bhow\s+to\b", re.IGNORECASE),
    re.compile(r"\bsteps?\s+to\b", re.IGNORECASE),
    re.compile(r"\bguide\b", re.IGNORECASE),
    re.compile(r"\btutorial\b", re.IGNORECASE),
)
_CAUSAL_PATTERNS = (
    re.compile(r"\bwhy\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+causes?\b", re.IGNORECASE),
    re.compile(r"\breason\s+for\b", re.IGNORECASE),
)
_COMMERCIAL_PRICING_PATTERNS = (
    re.compile(r"\bprice\b", re.IGNORECASE),
    re.compile(r"\bpricing\b", re.IGNORECASE),
    re.compile(r"\bcost\b", re.IGNORECASE),
    re.compile(r"\bhow\s+much\b", re.IGNORECASE),
)
_COMMERCIAL_COMPARISON_PATTERNS = (
    re.compile(r"\bvs\b", re.IGNORECASE),
    re.compile(r"\bversus\b", re.IGNORECASE),
    re.compile(r"\bcompare\b", re.IGNORECASE),
    re.compile(r"\bcomparison\b", re.IGNORECASE),
)


def normalize_intent_value(intent: str | None) -> str | None:
    normalized = str(intent or "").strip().lower()
    if normalized in INTENT_VALUES:
        return normalized
    return None


def normalize_query_type(query_type: str | None) -> str | None:
    normalized = str(query_type or "").strip().lower()
    if normalized in QUERY_TYPE_VALUES:
        return normalized
    return None


def query_type_from_intent(intent: str | None) -> str | None:
    normalized_intent = normalize_intent_value(intent)
    if not normalized_intent:
        return None
    return INTENT_TO_QUERY_TYPE.get(normalized_intent)


def resolve_query_type(*, query_type: str | None, intent: str | None = None) -> str | None:
    normalized_query_type = normalize_query_type(query_type)
    if normalized_query_type:
        return normalized_query_type
    return query_type_from_intent(intent)


def normalize_query_category(query_category: str | None) -> str | None:
    normalized = str(query_category or "").strip().lower().replace(" ", "_")
    if not normalized:
        return None
    normalized = QUERY_CATEGORY_ALIASES.get(normalized, normalized)
    if normalized in QUERY_CATEGORY_VALUES:
        return normalized
    return None


def classify_query_category(*, raw_query: str | None, query_category: str | None = None) -> str:
    normalized_query_category = normalize_query_category(query_category)
    if normalized_query_category:
        return normalized_query_category

    text = str(raw_query or "").strip().lower()
    if not text:
        return QUERY_CATEGORY_OTHER

    if any(pattern.search(text) for pattern in _COMMERCIAL_COMPARISON_PATTERNS):
        return QUERY_CATEGORY_COMMERCIAL_COMPARISON
    if any(pattern.search(text) for pattern in _COMMERCIAL_PRICING_PATTERNS):
        return QUERY_CATEGORY_COMMERCIAL_PRICING
    if any(pattern.search(text) for pattern in _CAUSAL_PATTERNS):
        return QUERY_CATEGORY_CAUSAL
    if any(pattern.search(text) for pattern in _INSTRUCTIONAL_PATTERNS):
        return QUERY_CATEGORY_INSTRUCTIONAL
    return QUERY_CATEGORY_OTHER


# ---------------------------------------------------------------------------
# Canonical, user-facing 5-type search taxonomy (Phase 4)
# ---------------------------------------------------------------------------
# The internal taxonomy above (query_type x query_category) is collapsed onto the
# five customer-facing search types shown under the AIO drilldown. ``comparison``
# is the premium (Specialist+) type. ``to_canonical`` is total: any input maps to
# exactly one canonical id, with ``category`` as the safe default for unknowns.

SEARCH_TYPE_BRAND = "brand"
SEARCH_TYPE_CATEGORY = "category"
SEARCH_TYPE_PROBLEM = "problem"
SEARCH_TYPE_FEATURE = "feature"
SEARCH_TYPE_COMPARISON = "comparison"

CANONICAL_SEARCH_TYPES = [
    SEARCH_TYPE_BRAND,
    SEARCH_TYPE_CATEGORY,
    SEARCH_TYPE_PROBLEM,
    SEARCH_TYPE_FEATURE,
    SEARCH_TYPE_COMPARISON,
]

PREMIUM_SEARCH_TYPES = {SEARCH_TYPE_COMPARISON}

SEARCH_TYPE_LABELS = {
    SEARCH_TYPE_BRAND: "Brand",
    SEARCH_TYPE_CATEGORY: "Category",
    SEARCH_TYPE_PROBLEM: "Problem",
    SEARCH_TYPE_FEATURE: "Feature",
    SEARCH_TYPE_COMPARISON: "Comparison",
}

# Internal query_category -> canonical search type. ``other`` deliberately falls
# through to the query_type-driven defaults below.
_CATEGORY_TO_CANONICAL = {
    QUERY_CATEGORY_COMMERCIAL_COMPARISON: SEARCH_TYPE_COMPARISON,
    QUERY_CATEGORY_COMMERCIAL_PRICING: SEARCH_TYPE_FEATURE,
    QUERY_CATEGORY_INSTRUCTIONAL: SEARCH_TYPE_PROBLEM,
    QUERY_CATEGORY_CAUSAL: SEARCH_TYPE_PROBLEM,
}

# query_type-driven defaults when the category is ``other``/unknown. Decision-making
# (transactional/navigational) intent leans brand-seeking; informational leans to the
# broad category bucket.
_QUERY_TYPE_TO_CANONICAL = {
    QUERY_TYPE_DECISION_MAKING: SEARCH_TYPE_BRAND,
    QUERY_TYPE_INFORMATIONAL: SEARCH_TYPE_CATEGORY,
}


def to_canonical(query_type: str | None, query_category: str | None) -> str:
    """Collapse internal (query_type, query_category) onto a canonical search type.

    Category is the more specific signal and wins; otherwise the query_type
    provides a default. Unknown / unrecognised inputs fall back to ``category``.
    """
    normalized_category = normalize_query_category(query_category)
    mapped = _CATEGORY_TO_CANONICAL.get(normalized_category)
    if mapped is not None:
        return mapped

    normalized_type = normalize_query_type(query_type)
    return _QUERY_TYPE_TO_CANONICAL.get(normalized_type, SEARCH_TYPE_CATEGORY)


def is_premium_search_type(search_type_id: str) -> bool:
    return search_type_id in PREMIUM_SEARCH_TYPES


# ---------------------------------------------------------------------------
# Stored search type (SIGV2-1186)
# ---------------------------------------------------------------------------
# ``to_canonical`` above, fed by ``classify_query_category``, derives a search
# type from the prompt's own words. That is a guess, and for anything the
# patterns do not recognise it is the documented ``category`` default rather
# than a reading of what the customer meant. A type guessed that way cannot
# answer "why is this prompt scored under Problem?", which is the question the
# ticket exists for.
#
# The type is therefore stored on the prompt (``ProjectVisibilityQuery.
# search_type``) and the text classifier is demoted to a suggestion used to
# pre-fill the field. ``resolve_search_type`` is the one function every scoring
# and serialisation path must call: the stored value wins, and the inference
# remains the fallback for the prompts written before the column existed, so
# nothing changes for them until they are retyped.

SEARCH_TYPE_SOURCE_STORED = "stored"
SEARCH_TYPE_SOURCE_INFERRED = "inferred"


def normalize_search_type(search_type: Any) -> str | None:
    """A canonical search-type id, or ``None`` for anything else.

    Accepts only the five customer-facing ids (case-insensitively, trimmed).
    Deliberately strict: the internal ``aeo``/``geo`` lane, the internal
    ``query_category`` vocabulary and free text are all rejected, so a bad value
    degrades to the inference instead of being stored as if the customer had
    chosen it. Booleans are rejected explicitly (``True`` is not ``"brand"``).
    """
    if not isinstance(search_type, str):
        return None
    normalized = search_type.strip().lower().replace(" ", "_").replace("-", "_")
    return normalized if normalized in set(CANONICAL_SEARCH_TYPES) else None


def suggest_search_type(raw_query: str | None, *, query_type: str | None = None) -> str:
    """The text-derived search type, offered as a suggestion.

    This is the pre-SIGV2-1186 behaviour, unchanged and total: pattern-match the
    prompt text onto an internal query category, then collapse it with
    ``to_canonical``. It is what the UI pre-fills when a customer types a
    free-form prompt, and the fallback for a prompt with no stored type. It is
    never authoritative when a stored type exists.
    """
    return to_canonical(query_type, classify_query_category(raw_query=raw_query))


def resolve_search_type(
    *,
    stored: Any,
    raw_query: str | None,
    query_type: str | None = None,
) -> str:
    """The search type scoring must use: the stored one, else the suggestion.

    Always returns a canonical id.
    """
    normalized = normalize_search_type(stored)
    if normalized is not None:
        return normalized
    return suggest_search_type(raw_query, query_type=query_type)


def search_type_source(stored: Any) -> str:
    """Whether a resolved type came from the prompt or from its text.

    Serialised next to the type itself so a surface can say "you chose this"
    rather than presenting a guess as a fact.
    """
    return (
        SEARCH_TYPE_SOURCE_STORED
        if normalize_search_type(stored) is not None
        else SEARCH_TYPE_SOURCE_INFERRED
    )


def search_type_coverage(resolved_search_types: Iterable[Any]) -> list[dict[str, Any]]:
    """Which of the five types the project's prompts actually cover.

    Takes the already-resolved type of each prompt in scope (active prompts
    only, resolved via :func:`resolve_search_type`) and returns one entry per
    canonical type, always in :data:`CANONICAL_SEARCH_TYPES` order, shaped
    ``{id, label, premium, prompt_count, covered}``.

    This is the honest half of the answer to "how can you rank me on something I
    never asked about": a type with no prompt is a gap in what the customer
    asked for, and it is stated before a scan runs instead of surfacing later as
    an unexplained ``unmeasured`` card. Values that are not canonical ids are
    ignored rather than bucketed somewhere, so a malformed row cannot invent
    coverage.
    """
    counts: dict[str, int] = {search_type: 0 for search_type in CANONICAL_SEARCH_TYPES}
    for value in resolved_search_types or []:
        normalized = normalize_search_type(value)
        if normalized is not None:
            counts[normalized] += 1

    return [
        {
            "id": search_type,
            "label": SEARCH_TYPE_LABELS[search_type],
            "premium": search_type in PREMIUM_SEARCH_TYPES,
            "prompt_count": counts[search_type],
            "covered": counts[search_type] > 0,
        }
        for search_type in CANONICAL_SEARCH_TYPES
    ]


SOURCE_MEASURED = "measured"
SOURCE_UNMEASURED = "unmeasured"
# SIGV2-1182: no measurement yet, but a run that will produce one is queued or
# in flight. "Nothing will happen" and "wait a moment" are different answers and
# the customer-facing card has to be able to tell them apart.
SOURCE_PENDING = "pending"


def _coerce_search_type_score(value: Any) -> float | None:
    """Defensively coerce a sub-score to a clamped float (0-100) or ``None``.

    Booleans are rejected (they are ``int`` subclasses but never valid scores).
    Non-numeric / missing values yield ``None`` so the type renders as "no data".
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, parsed))


def _coerce_answer_ratio(value: Any) -> dict[str, int] | None:
    """Coerce an answer ratio to ``{"present": int, "measured": int}`` or ``None``.

    ``measured`` must be positive and ``present`` cannot exceed it: a ratio the
    recorded data cannot support is ``None``, never ``0 of 0``.
    """
    if not isinstance(value, dict):
        return None
    try:
        measured = int(value["measured"])
        present = int(value["present"])
    except (KeyError, TypeError, ValueError):
        return None
    if measured <= 0 or present < 0 or present > measured:
        return None
    return {"present": present, "measured": measured}


def _search_type_insight(label: str, score: float | None, *, pending: bool = False) -> str:
    noun = label.lower()
    if score is None:
        if pending:
            # SIGV2-1182: the card's own sentence has to agree with its chip.
            # "No signal available yet" next to "a run is in progress" is the
            # same contradiction the ticket is about.
            return f"Measuring {noun} search visibility now."
        return f"No {noun} search-type signal available yet."
    if score >= 70:
        return f"Strong {noun} search visibility."
    if score >= 40:
        return f"Moderate {noun} search visibility."
    return f"Limited {noun} search visibility."


def aggregate_search_types(
    measurements: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build the 5 canonical search-type entries from measured visibility only.

    Returns one entry per canonical search type, always in
    :data:`CANONICAL_SEARCH_TYPES` order, shaped as
    ``{id, label, score, answer_ratio, trend, insight, premium, source}``.

    ``measurements`` comes from
    :func:`services.project_visibility_service.compute_search_type_measurements`
    and carries, per canonical type, the mean visibility over the project's own
    ``ProjectVisibilityQuery`` runs and the answers those runs actually looked at.
    A type with a measured score is tagged ``"source": "measured"``; a type with
    no score but a queued or running measurement is ``"source": "pending"``
    (SIGV2-1182, the ``pending`` flag the caller computed); anything else is
    ``"source": "unmeasured"``. Both non-measured states carry ``score: null``:
    pending describes what is happening, it does not invent a figure.

    There is deliberately no estimate here. Until SIGV2-1105 a type with no
    measured value fell back to a heuristic mapping of unrelated audit sub-scores
    (``scores.seo`` onto Feature, ``scores.aeo`` onto Category, and so on) tagged
    ``"source": "derived"`` and labelled "Estimated" on screen. Those are
    different quantities, not approximations of per-type visibility: with no
    ``entity_analysis`` or ``geo_signals`` in the report the five collapsed onto
    three distinct numbers, which is why the cards read as repeated. A figure
    nobody measured is not shown; the unmeasured state says so instead.

    ``trend`` is always ``None`` (no historical comparison at response time).
    This function never raises on malformed input; all five ids are always
    present and ``measurements=None`` yields five unmeasured entries.
    """
    measured = measurements if isinstance(measurements, dict) else {}

    result: list[dict[str, Any]] = []
    for search_type_id in CANONICAL_SEARCH_TYPES:
        label = SEARCH_TYPE_LABELS[search_type_id]
        entry = measured.get(search_type_id)
        entry = entry if isinstance(entry, dict) else {}
        raw = _coerce_search_type_score(entry.get("score"))
        score = int(round(raw)) if raw is not None else None
        pending = score is None and entry.get("pending") is True
        if score is not None:
            source = SOURCE_MEASURED
        else:
            source = SOURCE_PENDING if pending else SOURCE_UNMEASURED
        result.append(
            {
                "id": search_type_id,
                "label": label,
                "score": score,
                "answer_ratio": _coerce_answer_ratio(entry.get("answer_ratio")),
                "trend": None,
                "insight": _search_type_insight(label, score, pending=pending),
                "premium": search_type_id in PREMIUM_SEARCH_TYPES,
                "source": source,
            }
        )
    return result
