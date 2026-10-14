from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from app.config.plans import resolve_entitled_subscription_plan, resolve_plan_alias
from services.reports.audit_result_adapter import to_canonical_audit_result


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _coerce_competitor_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.startswith("http://") or normalized.startswith("https://"):
        return normalized
    if "." in normalized and " " not in normalized:
        return f"https://{normalized}"
    return None


def _score_breakdown(score: float | None) -> dict[str, Any]:
    return {
        "score": score,
        "components": {},
        "penalties": [],
        "bonuses": [],
    }


def _resolve_primary_title(audit_record: Any, canonical_report: Mapping[str, Any]) -> str:
    target = (
        canonical_report.get("target")
        if isinstance(canonical_report.get("target"), Mapping)
        else {}
    )
    site = canonical_report.get("site") if isinstance(canonical_report.get("site"), Mapping) else {}
    for candidate in (
        getattr(audit_record, "target_name", None),
        getattr(audit_record, "target_url", None),
        getattr(audit_record, "url", None),
        target.get("name"),
        target.get("url"),
        site.get("url"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return "Primary site"


def _canonicalize_audit_report(audit_record: Any) -> dict[str, Any]:
    raw_report = (
        audit_record.full_report
        if isinstance(getattr(audit_record, "full_report", None), Mapping)
        else {}
    )
    user = getattr(audit_record, "user", None)
    subscription_plan = resolve_plan_alias(resolve_entitled_subscription_plan(user))
    trial_plan = resolve_plan_alias(getattr(user, "trial_plan", None))
    effective_plan = subscription_plan or trial_plan or "plan_starter"
    return to_canonical_audit_result(
        dict(raw_report),
        audit_url=getattr(audit_record, "target_url", None) or getattr(audit_record, "url", None),
        audit_target_type=(
            getattr(getattr(audit_record, "audit_target_type", None), "value", None)
            or getattr(audit_record, "audit_target_type", None)
            or "website"
        ),
        target_name=getattr(audit_record, "target_name", None),
        target_url=getattr(audit_record, "target_url", None),
        target_metadata=getattr(audit_record, "target_metadata", None),
        created_at=getattr(audit_record, "created_at", None),
        plan=effective_plan,
    )


def _normalize_competitors(canonical_report: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_competitors = canonical_report.get("competitors")
    if not isinstance(raw_competitors, list):
        return []

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw_competitors):
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        normalized.append(
            {
                "key": f"{index}:{name.lower()}",
                "name": name,
                "rank": int(item.get("rank")) if isinstance(item.get("rank"), int) else None,
                "overall": _as_float(item.get("score")),
                "geo": _as_float(item.get("geo_visibility")),
                "aeo": _as_float(item.get("aeo_score")),
                "entity_strength": _as_float(item.get("entity_strength")),
                "source": str(item.get("source") or "canonical").strip() or "canonical",
                "confidence_score": _as_float(item.get("confidence_score")),
            }
        )
    return normalized


def _select_competitor(
    competitors: list[dict[str, Any]],
    *,
    competitor_name: str | None = None,
    competitor_rank: int | None = None,
) -> dict[str, Any]:
    if not competitors:
        raise ValueError("Selected audit does not contain competitor data for a battle report.")

    normalized_name = (
        competitor_name.strip().lower()
        if isinstance(competitor_name, str) and competitor_name.strip()
        else None
    )
    if normalized_name is not None:
        for competitor in competitors:
            if str(competitor.get("name") or "").strip().lower() == normalized_name:
                return competitor
        raise ValueError(
            f'Competitor "{competitor_name.strip()}" is not present in the selected audit.'
        )

    if competitor_rank is not None:
        for competitor in competitors:
            if competitor.get("rank") == competitor_rank:
                return competitor
        raise ValueError(f"Competitor rank {competitor_rank} is not present in the selected audit.")

    return competitors[0]


def build_canonical_competitor_battle_pair(
    audit_record: Any,
    *,
    competitor_name: str | None = None,
    competitor_rank: int | None = None,
) -> dict[str, Any]:
    if audit_record is None:
        raise ValueError("Selected audit is required for battle report generation.")

    left_report = _canonicalize_audit_report(audit_record)
    selected_competitor = _select_competitor(
        _normalize_competitors(left_report),
        competitor_name=competitor_name,
        competitor_rank=competitor_rank,
    )

    right_report = deepcopy(left_report)
    right_title = str(selected_competitor["name"])
    right_url = _coerce_competitor_url(right_title)

    overall_score = selected_competitor.get("overall")
    geo_score = selected_competitor.get("geo") or overall_score
    aeo_score = selected_competitor.get("aeo") or overall_score
    seo_score = overall_score
    entity_strength = selected_competitor.get("entity_strength") or 0.0

    right_report["target"] = {
        "type": "website",
        "name": right_title,
        "url": right_url,
        "metadata": {
            "comparison_source": "canonical_competitor_summary",
            "source": selected_competitor.get("source"),
        },
    }
    right_report["site"] = {
        **dict(right_report.get("site") or {}),
        "url": right_url,
    }
    right_report["seo"] = {
        **dict(right_report.get("seo") or {}),
        "onpage": seo_score,
        "performance": overall_score,
        "indexing": seo_score,
        "technical_seo": overall_score,
    }
    right_report["geo"] = {
        **dict(right_report.get("geo") or {}),
        "visibility_index": geo_score,
        "brand_anchor": entity_strength,
    }
    right_report["aeo"] = {
        **dict(right_report.get("aeo") or {}),
        "answerability_score": aeo_score,
    }
    right_report["entities"] = []
    right_report["competitors"] = []
    right_report["suggestions"] = []
    right_report["hallucination"] = None
    right_report["scores"] = {
        "seo": seo_score,
        "geo": geo_score,
        "aeo": aeo_score,
        "overall": overall_score,
        "seo_breakdown": _score_breakdown(seo_score),
        "geo_breakdown": _score_breakdown(geo_score),
        "aeo_breakdown": _score_breakdown(aeo_score),
        "scoring_version": (
            str((right_report.get("scores") or {}).get("scoring_version") or "3.0")
        ),
    }

    metadata = dict(right_report.get("metadata") or {})
    metadata["competitor_summary"] = {
        "derived_from_canonical_competitor": True,
        "selected_competitor_name": right_title,
        "confidence_score": selected_competitor.get("confidence_score"),
    }
    metadata["entity_analysis"] = {
        "entity_clarity_score": entity_strength,
        "brand_trust_score": entity_strength,
        "knowledge_graph_presence": False,
        "dominant_entities": [],
    }
    technical_signals = dict(metadata.get("technical_signals") or {})
    performance = dict(technical_signals.get("performance") or {})
    performance["score"] = overall_score
    technical_signals["performance"] = performance
    metadata["technical_signals"] = technical_signals
    metadata["executive_summary"] = (
        f"{right_title} benchmark snapshot from the selected audit. "
        f"Overall {int(round(overall_score or 0))}/100, "
        f"GEO {int(round(geo_score or 0))}/100, "
        f"AEO {int(round(aeo_score or 0))}/100."
    )
    right_report["metadata"] = metadata

    return {
        "left_title": _resolve_primary_title(audit_record, left_report),
        "right_title": right_title,
        "left_report": left_report,
        "right_report": right_report,
        "left_full_report": left_report,
        "right_full_report": right_report,
        "left_audit_record": audit_record,
        "right_audit_record": None,
    }


__all__ = ["build_canonical_competitor_battle_pair"]
