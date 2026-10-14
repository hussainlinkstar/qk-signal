"""Base prompt catalogue: the five search types a project starts with (SIGV2-1186).

Why this exists
---------------
A project used to contain only what the customer typed into "Add prompt". If
they typed three vague prompts, four of the five customer-facing search types
had nothing measuring them. ``aggregate_search_types`` then reported those four
as ``unmeasured`` with ``score: null`` and no estimate (SIGV2-1105, which must
stay), and the product could not tell the customer what was missing. Edward's
objection is the honest summary: if nothing the customer asked for leads to an
answer about their buyers' problems, we cannot rank them on it. The churn risk
is the same sentence from the other side: vague prompts in, hollow product out.

What this module is
-------------------
A deterministic template catalogue, one entry per canonical search type, filled
from data the project already holds. It is a pure function: no database, no
network, no LLM, no clock, no randomness. Project creation can therefore call
it inline, and the same call for the same project always produces the same five
prompts.

Why templates and not a model call
----------------------------------
Three reasons, in order of weight.

1. Project creation is a request path with a 1.5s budget (AGENTS.md 7.1), and
   an LLM call there would either block it or make the base set arrive
   asynchronously, which is the same "empty project" problem one layer down.
2. A generator that can fail is a generator that sometimes leaves a type
   uncovered, which is the defect being fixed. This one cannot fail: it always
   emits five prompts, one per type, or raises on a project with no name at all.
3. The repository already has this exact pattern and it works:
   ``DEFAULT_VOLATILITY_SEED_QUERIES`` in
   ``services/ai_search_volatility_service.py`` is a committed catalogue of seed
   queries per industry, inserted with ``source="default_catalog"``.

An LLM-refined variant is a sensible follow-up rather than a replacement: the
inputs it would need (a real industry label, a human-readable market, the site's
own description) are already produced by ``services.pre_scan_service.
analyze_target``, and :class:`BasePromptContext` accepts all three so an
enriching caller can pass them without touching the templates. If that variant
is built it must obey the LLM rules in AGENTS.md 4.4 / 8: the prompt text goes
in ``backend/prompts/``, the model comes from ``Settings``, never a literal, and
the call goes through the ai-service container rather than a router.

Attribution
-----------
Every prompt written from this catalogue is stored with
``ProjectVisibilityQuery.origin = "generated"`` so the customer can see which
prompts are ours, change their type, or delete them. The catalogue never writes
to the database; ``services.base_prompt_service`` does that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from services.query_taxonomy import (
    CANONICAL_SEARCH_TYPES,
    SEARCH_TYPE_BRAND,
    SEARCH_TYPE_CATEGORY,
    SEARCH_TYPE_COMPARISON,
    SEARCH_TYPE_FEATURE,
    SEARCH_TYPE_PROBLEM,
    normalize_search_type,
)

# The storage limit enforced by ``ProjectVisibilityService._normalize_query_text``.
# Nothing this module emits may exceed it, or the insert would 422.
MAX_BASE_PROMPT_CHARS = 500

# A free-text project field (pain points, USP) is up to 5000 characters. Only a
# short clause of it belongs inside a prompt; the rest would make a question no
# assistant answers usefully.
MAX_CLAUSE_CHARS = 120

ORIGIN_CUSTOMER = "customer"
ORIGIN_GENERATED = "generated"

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")


def _clean(value: str | None) -> str | None:
    """Collapse a project field to a single-line clause, or ``None``.

    Control characters (including the newlines and tabs a textarea field
    collects) become spaces, runs of whitespace collapse, and the result is
    trimmed. A blank field is ``None`` so the templates can branch on presence
    rather than on emptiness.
    """
    if not isinstance(value, str):
        return None
    text = _CONTROL_CHARS_RE.sub(" ", value)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text or None


def _clause(value: str | None, *, max_chars: int = MAX_CLAUSE_CHARS) -> str | None:
    """A short, readable clause taken from a long free-text field.

    Takes the first sentence when there is one, drops trailing punctuation so it
    can be embedded in a question, and trims on a word boundary rather than
    mid-word: a prompt ending "...alph" reads as a bug, not as a summary.
    """
    text = _clean(value)
    if text is None:
        return None

    first_sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip()
    text = first_sentence or text
    text = text.rstrip(" .,;:!?-")

    if len(text) > max_chars:
        head = text[: max_chars + 1]
        cut = head.rfind(" ")
        text = (head[:cut] if cut > 0 else text[:max_chars]).rstrip(" .,;:!?-")

    return text or None


@dataclass(frozen=True)
class BasePromptContext:
    """Everything the catalogue is allowed to know about a project.

    ``brand`` is the only required field, because it is the only one a project
    is guaranteed to have (``ProjectCreateRequest.name`` is mandatory). Every
    other field is optional and each template states its own fallback, so a
    project created with nothing but a name still gets five usable prompts
    instead of a template with an empty slot in it.

    ``industry``, ``market`` and ``description`` are the enrichment inputs. The
    project table stores none of them: ``target_country`` is an ISO alpha-2 code,
    and "GB" inside a customer-facing prompt reads as a bug, so the market is
    used only when a caller supplies a human-readable one (as
    ``services.pre_scan_service.analyze_target`` does, via ``market_region``).
    """

    brand: str
    domain: str | None = None
    industry: str | None = None
    market: str | None = None
    description: str | None = None
    audience: str | None = None
    problem: str | None = None
    competitor: str | None = None


@dataclass(frozen=True)
class GeneratedPrompt:
    """One catalogue entry: the prompt text and the type it was written for.

    The type travels with the text and is stored on the row, which is the whole
    point: a generated Problem prompt is scored as Problem because that is what
    it was written to be, not because its wording happened to trip a regex.
    """

    search_type: str
    query_text: str


def _brand_prompt(context: BasePromptContext) -> str:
    return f"What is {context.brand} and what does it offer?"


# SIGV2-1288: a discovery prompt may never name the brand.
#
# Five types, two jobs. Brand, Feature and Comparison are brand-anchored: the
# customer's name belongs in the question, because the question is what the
# engines say about them. Category and Problem are discovery: the question is
# whether an engine volunteers them to somebody who has not heard of them. A
# prompt that contains the brand cannot measure that, because it has already
# supplied the answer, and whatever score comes back is about recall of a name
# we just handed over.
#
# Both discovery templates used to fall back to naming the brand when they had
# nothing else. Edward caught the Problem one on a consultancy: "This is NAMING
# Tessiant, the prompt is what problems does it solve". The Category fallback
# had the same defect one line up.
#
# They now return None when there is nothing to anchor on. An absent prompt is
# visible: the coverage surface already shows an uncovered type and offers a
# suggestion the customer can edit. A brand-naming prompt filed under a
# discovery type is invisible, and it quietly measures the wrong thing forever.


def _category_prompt(context: BasePromptContext) -> str | None:
    industry = _clause(context.industry, max_chars=60)
    market = _clause(context.market, max_chars=60)
    audience = _clause(context.audience, max_chars=60)

    if industry and market:
        return f"What are the best {industry} providers in {market}?"
    if industry:
        return f"What are the best {industry} providers?"
    if audience:
        return f"What are the best tools for {audience}?"
    return None


def _problem_prompt(context: BasePromptContext) -> str | None:
    problem = _clause(context.problem)
    industry = _clause(context.industry, max_chars=60)
    audience = _clause(context.audience, max_chars=60)

    if problem:
        return f"What are the best solutions for {problem}?"
    if industry and audience:
        return f"What problems do {audience} hire a {industry} to solve?"
    if industry:
        return f"What problems does a {industry} solve for its clients?"
    if audience:
        return f"What problems do {audience} most often need help with?"
    return None


def _feature_prompt(context: BasePromptContext) -> str:
    return f"What does {context.brand} cost and what features are included?"


def _comparison_prompt(context: BasePromptContext) -> str:
    competitor = _clause(context.competitor, max_chars=60)
    industry = _clause(context.industry, max_chars=60)

    if competitor:
        return f"How does {context.brand} compare to {competitor}?"
    if industry:
        return f"How does {context.brand} compare to other {industry} providers?"
    return f"How does {context.brand} compare to its main alternatives?"


# Offered when there is nothing to anchor a discovery prompt on. The bracketed
# slot is deliberate and customer-facing: it is a question they finish, not one
# we guess at.
_UNANCHORED_SUGGESTIONS = {
    SEARCH_TYPE_CATEGORY: "What are the best [your category] providers?",
    SEARCH_TYPE_PROBLEM: "What are the best solutions for [the problem you solve]?",
}


_TEMPLATES = {
    SEARCH_TYPE_BRAND: _brand_prompt,
    SEARCH_TYPE_CATEGORY: _category_prompt,
    SEARCH_TYPE_PROBLEM: _problem_prompt,
    SEARCH_TYPE_FEATURE: _feature_prompt,
    SEARCH_TYPE_COMPARISON: _comparison_prompt,
}


def _render(context: BasePromptContext, search_type: str) -> str:
    """The prompt for one type, or an empty string when none can be written.

    A discovery template with nothing to anchor on returns ``None``; empty
    string is how that reaches callers, which already drop a blank prompt.
    """
    rendered = _TEMPLATES[search_type](context)
    if rendered is None:
        return ""
    text = _clean(rendered) or ""
    if len(text) > MAX_BASE_PROMPT_CHARS:
        head = text[: MAX_BASE_PROMPT_CHARS - 1]
        cut = head.rfind(" ")
        text = f"{(head[:cut] if cut > 0 else head).rstrip(' .,;:!?-')}?"
    return text


def normalize_brand(name: str | None) -> str | None:
    """The brand label used in every template, or ``None`` if there is none."""
    return _clause(name, max_chars=80)


# Labels a domain can end in that are not part of the brand.
_PUBLIC_SUFFIX_HEADS = {"co", "com", "net", "org", "gov", "edu", "ac"}


def brand_from_domain(domain: str | None) -> str | None:
    """The brand a domain declares, or ``None`` if it declares none.

    SIGV2-1288: prompts were built from ``project.name``, which is a label the
    customer chose for a container. Edward's read "prompt picks up the project
    name not the company name", and a prompt naming "Q4 test" or "Tessiant
    website" measures a string that does not exist in the world.

    The domain is the identity the audit actually measures, so the registrable
    label is the better brand: ``tessiant.com`` is Tessiant whatever the
    project happens to be called.

    This is a correction, not the answer. A brand whose domain is an
    abbreviation (``tsnt.io``) still deserves to be asked about by name, and
    that needs a brand field on the project rather than inference. Recorded on
    the ticket.
    """
    raw = (domain or "").strip().lower()
    if not raw:
        return None
    for prefix in ("https://", "http://"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
    raw = raw.split("/")[0].split("?")[0].split("@")[-1].split(":")[0]
    if raw.startswith("www."):
        raw = raw[4:]
    labels = [label for label in raw.split(".") if label]
    if len(labels) < 2:
        return None
    # Walk past the public suffix: "example.co.uk" and "example.com" both land
    # on "example".
    candidate = labels[-2]
    if candidate in _PUBLIC_SUFFIX_HEADS and len(labels) >= 3:
        candidate = labels[-3]
    if not candidate or candidate in _PUBLIC_SUFFIX_HEADS:
        return None
    # Hyphens and underscores read as spaces in a question.
    words = [part for part in candidate.replace("_", "-").split("-") if part]
    if not words:
        return None
    return _clause(" ".join(word[:1].upper() + word[1:] for word in words), max_chars=80)


def generate_base_prompts(context: BasePromptContext) -> list[GeneratedPrompt]:
    """The project's base prompt set: one prompt per canonical search type.

    Always returns exactly five entries, in
    :data:`services.query_taxonomy.CANONICAL_SEARCH_TYPES` order, each carrying
    the type it was written for. Pure and deterministic.
    """
    return [
        GeneratedPrompt(search_type=search_type, query_text=_render(context, search_type))
        for search_type in CANONICAL_SEARCH_TYPES
    ]


def suggest_prompt_for_search_type(
    context: BasePromptContext,
    search_type: str | None,
) -> str | None:
    """The single prompt that would fill one named gap, or ``None``.

    This is what the coverage surface offers for an uncovered type, so the
    suggestion a customer is shown is the same sentence the generator would have
    written. A non-canonical type yields ``None`` rather than a default
    template: offering a Category prompt to someone who asked about something
    else is the guessing this ticket removes.
    """
    normalized = normalize_search_type(search_type)
    if normalized is None:
        return None
    rendered = _render(context, normalized)
    if rendered:
        return rendered
    # SIGV2-1288: a discovery type we cannot anchor yields no prompt to create,
    # but the customer still needs something to act on. A fill-in-the-blank is
    # honest about what is missing and takes one edit to finish. The old
    # behaviour put the brand name into the question instead, which read as
    # complete and measured recall of a name we had just supplied.
    return _UNANCHORED_SUGGESTIONS.get(normalized)
