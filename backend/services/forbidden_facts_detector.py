"""Deterministic detector for claims that assert FORBIDDEN brand facts.

Guardrails goal-(b). Given AI-generated claim texts and a project's
``is_forbidden`` brand facts, flag any claim that asserts a forbidden statement
as true.

Design constraints (see AGENTS.md §4.4 / §8):
  * PURE & deterministic — no LLM, no I/O, no randomness. Unit-testable.
  * HIGH PRECISION — tuned to favour FALSE-NEGATIVES over false-positives
    (under-flag rather than over-flag). It only flags a claim when EVERY
    significant content token of the forbidden assertion is present in the
    claim, those tokens co-occur within a small PROXIMITY WINDOW (so incidental
    far-apart co-occurrences are ignored), AND the claim is not negated.
  * ADDITIVE — callers pass an (optional) list of forbidden statements; an
    empty list yields no matches and therefore zero behaviour change.

This module never lowers a grounding threshold. It can only surface ADDITIONAL
contradictions that the caller may use to make grounding stricter (flag more),
never looser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Words that frame a forbidden fact as an instruction ("Do not state we are the
# market leader") rather than content. Stripped before building the signature so
# the comparison is against the asserted content ("market leader").
_FRAMING_TOKENS: frozenset[str] = frozenset(
    {
        "do",
        "not",
        "dont",
        "never",
        "avoid",
        "refrain",
        "claim",
        "claims",
        "claiming",
        "claimed",
        "state",
        "stating",
        "stated",
        "say",
        "saying",
        "said",
        "mention",
        "mentioning",
        "imply",
        "implying",
        "assert",
        "asserting",
        "describe",
        "describing",
        "that",
        "the",
        "and",
        "are",
        "our",
        "your",
        "should",
        "must",
        "cannot",
        "being",
    }
)

# Generic, low-signal tokens that should not count toward a forbidden signature
# (they appear in too many unrelated claims to be discriminating).
_STOPWORDS: frozenset[str] = frozenset(
    {
        "for",
        "from",
        "has",
        "have",
        "its",
        "was",
        "were",
        "will",
        "with",
        "this",
        "their",
        "they",
        "them",
        "use",
        "uses",
        "using",
        "all",
        "any",
        "can",
        "may",
    }
)

# Minimum number of significant tokens a forbidden statement must contribute to
# be considered a usable signature. Single-token signatures are skipped to avoid
# over-flagging on a common word (favours false-negatives).
_MIN_SIGNATURE_TOKENS = 2

# Extra slack added to the signature length to size the proximity window. A claim
# only asserts the forbidden fact when ALL signature tokens co-occur inside a
# sliding window of ``len(signature) + _PROXIMITY_SLACK`` tokens, so the tokens
# must be CLOSE TOGETHER (not merely present somewhere far apart). This tightens
# precision; it can only ever make the detector flag FEWER claims, never more.
_PROXIMITY_SLACK = 4

# Negation cues in a CLAIM. If present, the claim is treated as NOT asserting the
# forbidden fact (e.g. "We are not the market leader") and is left unflagged.
_NEGATION_RE = re.compile(
    r"(?:\bnot\b|\bno\b|\bnever\b|\bwithout\b|\bcannot\b|\bcan't\b|\bdon't\b|"
    r"\bdoesn't\b|\bdidn't\b|\bisn't\b|\baren't\b|\bwasn't\b|\bweren't\b|"
    r"\bneither\b|\bnor\b|n't\b|\bnon-)",
    re.IGNORECASE,
)

_WORD_RE = re.compile(r"[a-zA-Z0-9]+")


@dataclass(frozen=True)
class ForbiddenMatch:
    """A claim that asserts a forbidden brand fact."""

    claim_index: int
    claim_text: str
    forbidden_statement: str
    matched_tokens: list[str] = field(default_factory=list)


def _tokenize(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(str(text or "").lower()) if len(w) > 2]


def build_forbidden_signature(statement: str) -> list[str]:
    """Return the significant content tokens of a forbidden statement.

    Strips instruction framing ("do not state", "we should never claim") and
    low-signal stopwords, returning the deduplicated content tokens that a
    contradicting claim would have to assert. Returns ``[]`` when the statement
    has too little discriminating content to match precisely.
    """
    signature: list[str] = []
    seen: set[str] = set()
    for token in _tokenize(statement):
        if token in _FRAMING_TOKENS or token in _STOPWORDS:
            continue
        if token in seen:
            continue
        seen.add(token)
        signature.append(token)
    if len(signature) < _MIN_SIGNATURE_TOKENS:
        return []
    return signature


def claim_asserts_forbidden(claim_text: str, signature: list[str]) -> bool:
    """True iff the claim asserts the forbidden signature as fact.

    High precision: requires the claim to be free of negation cues, EVERY
    signature token to be present, AND those tokens to co-occur within a sliding
    proximity window of ``len(signature) + _PROXIMITY_SLACK`` tokens. Requiring
    proximity (not mere presence) prevents flagging claims where the signature
    tokens happen to appear far apart and unrelated. Any condition failing yields
    ``False`` (under-flag). This is strictly STRICTER than a bag-of-words match,
    so it can only ever flag fewer claims, never more.
    """
    if not signature:
        return False
    raw = str(claim_text or "")
    if not raw.strip():
        return False
    if _NEGATION_RE.search(raw):
        return False
    claim_tokens = _tokenize(raw)
    signature_set = set(signature)
    # Cheap precondition: every signature token must be present at all.
    if not signature_set.issubset(claim_tokens):
        return False
    # Precision: the signature tokens must also co-occur in CLOSE PROXIMITY.
    window = len(signature) + _PROXIMITY_SLACK
    last_start = max(1, len(claim_tokens) - window + 1)
    for start in range(last_start):
        if signature_set.issubset(claim_tokens[start : start + window]):
            return True
    return False


def detect_forbidden_contradictions(
    *,
    claim_texts: list[str],
    forbidden_statements: list[str],
) -> list[ForbiddenMatch]:
    """Flag claims that assert any forbidden statement as true.

    Pure and order-stable. Returns at most one match per claim index (the first
    forbidden statement it contradicts). An empty ``forbidden_statements`` (or
    empty ``claim_texts``) yields ``[]`` — i.e. zero behaviour change.
    """
    if not forbidden_statements or not claim_texts:
        return []

    signatures: list[tuple[str, list[str]]] = []
    for statement in forbidden_statements:
        signature = build_forbidden_signature(statement)
        if signature:
            signatures.append((str(statement).strip(), signature))
    if not signatures:
        return []

    matches: list[ForbiddenMatch] = []
    for index, claim_text in enumerate(claim_texts):
        for statement, signature in signatures:
            if claim_asserts_forbidden(claim_text, signature):
                matches.append(
                    ForbiddenMatch(
                        claim_index=index,
                        claim_text=str(claim_text or ""),
                        forbidden_statement=statement,
                        matched_tokens=list(signature),
                    )
                )
                break
    return matches
