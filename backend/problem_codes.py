"""Deterministic problem codes: durable identity for an Advisor fix.

A recommendation's text is written by an LLM on every audit, so its wording
drifts between runs. Keying a dismissal on that text (``sha256`` of the action)
means the customer's decision is lost as soon as the model rephrases the fix,
and the dismissed recommendation reappears. The product promise is explicit:
dismissing a fix suppresses it from FUTURE audits.

This module holds the one vocabulary in the audit pipeline that does not drift:
the deterministic checks of :class:`score_utils.DeterministicScoringEngine`.
Each check that can fail emits a penalty, and each penalty carries a ``code``
from the registry below. The code is produced by Python, from measured page
signals, so the same failing check yields the same code on every audit forever.
Dismissals key on that code; recommendations with no code keep the legacy text
hash (see :mod:`app.services.learnings_service`).

Design rules, in priority order:

1. **Identity must fail toward showing the fix.** A dismissed fix reappearing
   is visible to the customer and merely annoying. Suppressing a fix the
   customer never dismissed silently withholds advice they pay for, and nobody
   can see it happened. So every lookup here is exact and closed-world: an
   unknown or malformed code resolves to ``None`` and the caller falls back to
   the text hash, which can only ever under-suppress.
2. **No LLM and no fuzzy matching may assign a code.** A misclassification
   produces exactly the invisible failure of rule 1. Codes are attached at the
   deterministic source, before any model sees the text, and they travel with
   the recommendation unchanged.
3. **The registry is append-only in practice.** A stored dismissal holds
   ``problem:<code>`` as a literal string, so renaming or removing a code
   orphans customer decisions. Add codes; do not rewrite them.
"""

from __future__ import annotations

import re
from typing import Final, NamedTuple

#: Namespace for a problem-code suppression key. The stored
#: ``recommendation_decisions.action_fingerprint`` column is 64 chars and
#: otherwise holds a 64-char sha256 hex digest, which can never contain ``:``
#: or non-hex characters, so a prefixed code cannot collide with a legacy row.
PROBLEM_CODE_KEY_PREFIX: Final[str] = "problem:"

#: Longest accepted code. ``len(PROBLEM_CODE_KEY_PREFIX) + 48 <= 64`` keeps the
#: namespaced key inside the existing column width with no migration.
MAX_PROBLEM_CODE_CHARS: Final[int] = 48

_PROBLEM_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{2,47}$")

#: Impact thresholds over the absolute penalty points a failing check deducts.
#: Deterministic on purpose: the label is read off the score engine's own
#: weighting, never guessed and never asked of a model.
_HIGH_IMPACT_MIN_POINTS: Final[float] = 15.0
_MEDIUM_IMPACT_MIN_POINTS: Final[float] = 8.0


class ProblemDefinition(NamedTuple):
    """A deterministic problem and the fix seed offered for it.

    ``seed_action`` is the candidate action text fed into the suggestion
    pipeline. The enrichment step rewrites it into user-facing copy, which is
    exactly why identity cannot live in the text: the seed is phrased as an
    action so that even when enrichment is unavailable the fallback copy still
    tells the customer what to do.
    """

    code: str
    seed_action: str


# Deterministic checks in score_utils that a customer can act on. The three
# "Scraping failed, content-dependent checks skipped" penalties are deliberately
# absent: they describe our own fetch, not a fix the customer can make.
_DEFINITIONS: Final[tuple[ProblemDefinition, ...]] = (
    ProblemDefinition(
        "poor_lcp",
        "Reduce the page's Largest Contentful Paint so its main content renders faster.",
    ),
    ProblemDefinition(
        "poor_cls",
        "Reserve space for late-loading elements so the page stops shifting as it loads.",
    ),
    ProblemDefinition(
        "missing_canonical_url",
        "Add a canonical URL tag to the page.",
    ),
    ProblemDefinition(
        "missing_mobile_viewport",
        "Add a mobile viewport meta tag so the page renders correctly on phones.",
    ),
    ProblemDefinition(
        "page_noindex",
        "Remove the noindex robots directive so search engines can index the page.",
    ),
    ProblemDefinition(
        "title_too_short",
        "Expand the page title so it describes the page in full.",
    ),
    ProblemDefinition(
        "missing_page_title",
        "Add a descriptive title tag to the page.",
    ),
    ProblemDefinition(
        "meta_description_too_short",
        "Expand the meta description so it summarises the page in full.",
    ),
    ProblemDefinition(
        "missing_meta_description",
        "Add a unique meta description to the page.",
    ),
    ProblemDefinition(
        "multiple_h1_tags",
        "Reduce the page to a single H1 heading.",
    ),
    ProblemDefinition(
        "missing_h1",
        "Add one descriptive H1 heading to the page.",
    ),
    ProblemDefinition(
        "poor_alt_text_coverage",
        "Add descriptive alt text to the page's images.",
    ),
    ProblemDefinition(
        "thin_content",
        "Expand the page so it covers its topic in depth.",
    ),
    ProblemDefinition(
        "no_https",
        "Serve the page over HTTPS.",
    ),
    ProblemDefinition(
        "mixed_content",
        "Load every resource on the page over HTTPS instead of HTTP.",
    ),
    ProblemDefinition(
        "missing_entity_schema",
        "Add structured data that defines the page's main entity.",
    ),
    ProblemDefinition(
        "missing_aeo_schema",
        "Add answer-oriented structured data (FAQPage, QAPage or HowTo) to the page.",
    ),
    ProblemDefinition(
        "low_vocabulary_diversity",
        "Vary the page's wording so the content stops repeating the same terms.",
    ),
    ProblemDefinition(
        "content_too_complex",
        "Simplify the page's sentences so its reading level suits a general audience.",
    ),
    ProblemDefinition(
        "high_passive_voice",
        "Rewrite the page's passive sentences in active voice.",
    ),
    ProblemDefinition(
        "boilerplate_language",
        "Replace the page's filler phrases with specific, concrete statements.",
    ),
)

PROBLEM_DEFINITIONS: Final[dict[str, ProblemDefinition]] = {
    definition.code: definition for definition in _DEFINITIONS
}

KNOWN_PROBLEM_CODES: Final[frozenset[str]] = frozenset(PROBLEM_DEFINITIONS)


def normalize_problem_code(raw_code: object) -> str | None:
    """Return a known problem code, or ``None``.

    Closed-world by design (rule 1 in the module docstring): anything blank,
    malformed, over-long or absent from the registry resolves to ``None`` so the
    caller falls back to text-hash identity. An unknown code must never become a
    suppression key, because a key nobody can explain could hide a fix the
    customer never dismissed.
    """
    if not isinstance(raw_code, str):
        return None
    code = raw_code.strip().lower()
    if not code or len(code) > MAX_PROBLEM_CODE_CHARS:
        return None
    if not _PROBLEM_CODE_RE.match(code):
        return None
    return code if code in KNOWN_PROBLEM_CODES else None


def problem_code_key(raw_code: object) -> str | None:
    """Return the namespaced suppression key for a code, or ``None``.

    The key is stored verbatim in ``recommendation_decisions.action_fingerprint``
    instead of a digest: it is self-describing in the database, it cannot collide
    with the legacy sha256 hex digests, and it fits the existing column.
    """
    code = normalize_problem_code(raw_code)
    return f"{PROBLEM_CODE_KEY_PREFIX}{code}" if code else None


def is_problem_code_key(raw_key: object) -> bool:
    """Return True when a stored fingerprint is a problem-code key."""
    return isinstance(raw_key, str) and raw_key.strip().lower().startswith(PROBLEM_CODE_KEY_PREFIX)


def seed_action_for(raw_code: object) -> str | None:
    """Return the deterministic action seed for a known code, else ``None``."""
    code = normalize_problem_code(raw_code)
    return PROBLEM_DEFINITIONS[code].seed_action if code else None


def impact_label_for_points(raw_points: object) -> str:
    """Map a penalty's point deduction to an impact label, deterministically.

    Reads the score engine's own weighting rather than asking a model: a check
    worth 15+ points is high impact, 8+ is medium, the rest low. A missing or
    unreadable value degrades to ``"medium"``, matching the pipeline's existing
    default for an unrated suggestion.
    """
    try:
        points = abs(float(raw_points))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "medium"
    if points >= _HIGH_IMPACT_MIN_POINTS:
        return "high"
    if points >= _MEDIUM_IMPACT_MIN_POINTS:
        return "medium"
    return "low"


__all__ = [
    "KNOWN_PROBLEM_CODES",
    "MAX_PROBLEM_CODE_CHARS",
    "PROBLEM_CODE_KEY_PREFIX",
    "PROBLEM_DEFINITIONS",
    "ProblemDefinition",
    "impact_label_for_points",
    "is_problem_code_key",
    "normalize_problem_code",
    "problem_code_key",
    "seed_action_for",
]
