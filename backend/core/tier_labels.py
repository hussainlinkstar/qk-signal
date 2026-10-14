"""Canonical audit tier label mapping.

This is the **single source of truth** for user-facing audit tier names
used across the entire stack, API responses, PDF reports, email
templates, and the frontend constants mirror.

Internal tier IDs (``fast``, ``smart``, ``deep_judgment``) are stable
database / queue values and must **never** change.  Only the *display*
labels in this module are user-facing.
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────────────────────
# Canonical tier IDs, the superset of valid values stored in the DB.
# ──────────────────────────────────────────────────────────────────────
VALID_TIERS: frozenset[str] = frozenset({"lite", "fast", "smart", "deep_judgment"})

# ──────────────────────────────────────────────────────────────────────
# User-facing display labels
# ──────────────────────────────────────────────────────────────────────
TIER_DISPLAY_LABELS: dict[str, str] = {
    "lite": "Quick Scan",
    "fast": "Fast Audit",
    "smart": "Smart Audit",
    "deep_judgment": "Deep Analysis",
}

# Short labels (for badges, chips, compact UI)
TIER_SHORT_LABELS: dict[str, str] = {
    "lite": "Quick",
    "fast": "Fast",
    "smart": "Smart",
    "deep_judgment": "Deep",
}

# ──────────────────────────────────────────────────────────────────────
# Runtime per depth: NOT HERE, and not a constant anywhere (SIGV2-1177)
# ──────────────────────────────────────────────────────────────────────
# This module used to hold ``TIER_RUNTIME_ESTIMATES``, a hardcoded figure per
# depth, and ``get_tier_runtime_estimate`` to read it. Both are gone, and
# nothing should bring them back.
#
# The history is worth keeping, because the same mistake has now been made
# twice. The original figures (``~2 min`` / ``~8 min`` / ``~10 min``, plus
# ``~30 sec`` for lite) traced to nothing measured and contradicted the
# approved design. SIGV2-1161 replaced them with the approved design's own
# ``~5`` / ``~15`` / ``~45``, which is a real source but still not a
# measurement, and Jake's decision was to state no figure at all until the
# numbers come from recorded durations.
#
# SIGV2-1177 is that measurement. ``audit_jobs`` records ``tier``,
# ``started_at`` and ``completed_at`` per job, so the figure is derived from
# completed runs by ``services/tier_duration_stats_service.py``, stored in
# ``audit_tier_duration_stats`` by the hourly cron sweep, and served from
# ``GET /api/v1/audit/tier-durations``. Read it from there.
#
# The three rules that module enforces, repeated here because this is where
# someone looking for "the tier runtime constant" will land:
#
#   * The statistic is the interquartile range of completed runs, in minutes,
#     and the copy says exactly that. Do not restate it as a single figure.
#   * Below the minimum sample size, no figure exists and the surface states
#     nothing. Not a placeholder, not a zero, not "about 0 minutes".
#   * A tier with no measurement is simply absent from the payload. Do not
#     substitute another tier's number, the approved design's number, or a
#     guess about how long a scan feels.

# ──────────────────────────────────────────────────────────────────────
# Alias normalization, map legacy / variant IDs → canonical tier ID
# ──────────────────────────────────────────────────────────────────────
TIER_ALIASES: dict[str, str] = {
    "fast": "fast",
    "standard": "fast",
    "lite": "lite",
    "quick": "fast",
    "deep": "smart",
    "smart": "smart",
    "thorough": "smart",
    "deep_judgment": "deep_judgment",
    "high_confidence": "deep_judgment",
}


def normalize_tier(tier: str | None) -> str:
    """Resolve any tier alias to its canonical ID.  Falls back to ``"fast"``."""
    cleaned = str(tier or "").strip().lower()
    if not cleaned:
        return "fast"
    return TIER_ALIASES.get(cleaned, "fast")


def get_tier_display(tier: str | None) -> str:
    """Return the full user-facing display label for a tier."""
    return TIER_DISPLAY_LABELS.get(normalize_tier(tier), TIER_DISPLAY_LABELS["fast"])


def get_tier_short(tier: str | None) -> str:
    """Return the short badge/chip label for a tier."""
    return TIER_SHORT_LABELS.get(normalize_tier(tier), TIER_SHORT_LABELS["fast"])
