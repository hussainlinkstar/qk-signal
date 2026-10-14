"""Audit queue routing, maps audit tiers to priority Redis queues.

Producers call ``resolve_queue_for_tier(tier)`` to choose the correct
priority queue.  The worker consumes from ``ALL_CONSUMER_QUEUES`` in
priority order (fast → smart → deep) with the legacy ``audit_jobs``
queue as lowest-priority fallback.
"""

import os

_BASE_QUEUE = os.getenv("AUDIT_QUEUE_NAME", "audit_jobs")

QUEUE_FAST: str = f"{_BASE_QUEUE}:fast"
QUEUE_SMART: str = f"{_BASE_QUEUE}:smart"
QUEUE_DEEP: str = f"{_BASE_QUEUE}:deep"

# Backward-compatible alias for callers that still need the legacy single-queue name
LEGACY_QUEUE_NAME: str = _BASE_QUEUE

# Priority order for consumption: fast > smart > deep > legacy fallback
ALL_CONSUMER_QUEUES: list[str] = [QUEUE_FAST, QUEUE_SMART, QUEUE_DEEP, _BASE_QUEUE]

_TIER_QUEUE_MAP: dict[str, str] = {
    "fast": QUEUE_FAST,
    "lite": QUEUE_FAST,
    "smart": QUEUE_SMART,
    "deep": QUEUE_DEEP,
    "deep_judgment": QUEUE_DEEP,
}


def resolve_queue_for_tier(tier: str | None) -> str:
    """Return the priority queue name for a given audit tier."""
    return _TIER_QUEUE_MAP.get((tier or "fast").strip().lower(), QUEUE_FAST)
