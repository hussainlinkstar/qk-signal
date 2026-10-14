"""Deterministic AIO (AI Optimization) view derivation.

AIO is a customer-facing roll-up of the internal AEO + GEO scores. This is a
pure, additive view only: it never mutates the canonical audit analysis and
performs no I/O or LLM calls. Weights are configurable via Settings
(``AIO_AEO_WEIGHT`` / ``AIO_GEO_WEIGHT``); the default 50/50 yields the simple
mean of the present component scores.
"""

import math
from typing import Any, Optional

from core.config import settings


def _coerce_score(value: Any) -> Optional[float]:
    """Defensively coerce a score value to float.

    The canonical schema types ``*_score`` as ``Any``, so values may arrive as
    ints, floats, numeric strings, ``None`` or unrelated types. Non-numeric or
    missing values yield ``None`` (ignored from the roll-up). Booleans are
    rejected (they are technically ``int`` subclasses but never valid scores).
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def derive_aio(analysis: dict) -> dict:
    """Roll up AEO + GEO into an AIO view.

    Returns a dict with the weighted-mean ``aio_score`` (rounded to the nearest
    int, or ``None`` when neither component is present), the original component
    scores, the analysis summary, and the customer-facing scope label.
    """
    analysis = analysis or {}

    aeo_raw = analysis.get("aeo_score")
    geo_raw = analysis.get("geo_score")

    aeo = _coerce_score(aeo_raw)
    geo = _coerce_score(geo_raw)

    w_aeo = float(settings.AIO_AEO_WEIGHT)
    w_geo = float(settings.AIO_GEO_WEIGHT)

    # Half-up rounding (``floor(x + 0.5)``) to match the frontend fallback's
    # ``Math.round`` semantics; Python's built-in ``round`` uses banker's
    # rounding, which diverges on exact .5 means (e.g. 50.5 -> 50 vs 51).
    aio_score: Optional[int]
    if aeo is not None and geo is not None:
        weight_sum = w_aeo + w_geo
        if weight_sum == 0:
            # Degenerate config: fall back to a simple mean of the components.
            aio_score = int(math.floor((aeo + geo) / 2 + 0.5))
        else:
            aio_score = int(math.floor((w_aeo * aeo + w_geo * geo) / weight_sum + 0.5))
    elif aeo is not None:
        aio_score = int(math.floor(aeo + 0.5))
    elif geo is not None:
        aio_score = int(math.floor(geo + 0.5))
    else:
        aio_score = None

    return {
        "aio_score": aio_score,
        "components": {
            "aeo": aeo_raw if aeo is not None else None,
            "geo": geo_raw if geo is not None else None,
        },
        "summary": analysis.get("summary"),
        "scope": "website_and_brand",
    }


def attach_aio_view(report: Optional[dict]) -> Optional[dict]:
    """Attach the AIO roll-up to a report at ``metadata.aio`` (response-time only).

    This is a pure, additive augmentation: it never persists, and it never
    touches the canonical ``CanonicalAuditAnalysisContract``. The AEO/GEO inputs
    are read from the report's resolved ``scores`` (canonical shape) with a
    fallback to a legacy ``analysis`` block; ``derive_aio`` defensively handles
    missing or non-numeric values. ``metadata`` is a free-form dict, so adding
    the ``aio`` key is non-breaking. The call is idempotent.
    """
    if not isinstance(report, dict):
        return report

    analysis = report.get("analysis") if isinstance(report.get("analysis"), dict) else {}
    scores = report.get("scores") if isinstance(report.get("scores"), dict) else {}
    aio_source = {
        "aeo_score": analysis.get("aeo_score", scores.get("aeo")),
        "geo_score": analysis.get("geo_score", scores.get("geo")),
        "summary": analysis.get("summary"),
    }

    metadata = report.get("metadata") if isinstance(report.get("metadata"), dict) else {}
    metadata["aio"] = derive_aio(aio_source)
    report["metadata"] = metadata
    return report
