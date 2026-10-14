from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

import models


REFERENCE_AUDIT_CORPUS_SCHEMA_VERSION = "orchestra-v3-reference-corpus-1"
PROMPT_QUALITY_CALIBRATION_REPORT_SCHEMA_VERSION = "orchestra-v3-calibration-report-1"
REFERENCE_AUDIT_CORPUS_TIERS = ("fast", "smart", "deep_judgment")

_PIPELINE_PROMPT_FILE_MAP: dict[str, dict[str, tuple[str, ...]]] = {
    "fast_3step": {
        "generator": ("backend/prompts/fast/proposer.md",),
        "consolidator": ("backend/prompts/fast/synthesizer.md",),
        "magistrate": ("backend/prompts/fast/synthesizer.md",),
    },
    "smart_5step": {
        "generator": (
            "backend/prompts/smart/seo_generator.md",
            "backend/prompts/smart/aeo_geo_generator.md",
        ),
        "consolidator": ("backend/prompts/smart/synthesizer.md",),
        "magistrate": ("backend/prompts/smart/magistrate.md",),
    },
    "delta_flow": {
        "generator": (
            "backend/prompts/deep_judgment/seo_generator.md",
            "backend/prompts/deep_judgment/geo_generator.md",
            "backend/prompts/deep_judgment/aeo_generator.md",
        ),
        "critic": (
            "backend/prompts/deep_judgment/seo_critic.md",
            "backend/prompts/deep_judgment/geo_critic.md",
            "backend/prompts/deep_judgment/aeo_critic.md",
        ),
        "consolidator": ("backend/prompts/deep_judgment/consolidator.md",),
        "magistrate": ("backend/prompts/deep_judgment/global_magistrate.md",),
    },
}


def _coerce_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any) -> int | None:
    try:
        if value in ("", None):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _isoformat(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _extract_debate_payload(report: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}

    debate = report.get("debate")
    if isinstance(debate, dict):
        return debate

    metadata = report.get("metadata")
    if isinstance(metadata, dict):
        nested_debate = metadata.get("debate")
        if isinstance(nested_debate, dict):
            return nested_debate

    return {}


def _extract_quality_gate(report: dict[str, Any]) -> dict[str, Any]:
    debate = _extract_debate_payload(report)
    quality_gate = debate.get("quality_gate")
    return quality_gate if isinstance(quality_gate, dict) else {}


def _role_from_violation_code(code: str) -> str | None:
    if code.startswith("generator_"):
        return "generator"
    if code.startswith("consolidator_"):
        return "consolidator"
    if code.startswith("magistrate_"):
        return "magistrate"
    return None


def _prompt_files_for_violation_codes(
    *, pipeline_type: str, violation_codes: list[str]
) -> list[str]:
    pipeline_map = _PIPELINE_PROMPT_FILE_MAP.get(pipeline_type, {})
    prompt_files: list[str] = []

    for code in violation_codes:
        role = _role_from_violation_code(code)
        if role is None:
            continue
        prompt_files.extend(pipeline_map.get(role, ()))

    return sorted(dict.fromkeys(prompt_files))


class PromptQualityCalibrationService:
    def load_reference_manifest(self, *, path: str | Path) -> dict[str, Any]:
        manifest_path = Path(path).resolve()
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Reference audit corpus manifest must be a JSON object.")

        schema_version = _coerce_text(payload.get("schema_version"))
        if schema_version != REFERENCE_AUDIT_CORPUS_SCHEMA_VERSION:
            raise ValueError(
                "Reference audit corpus manifest schema_version must be "
                f"{REFERENCE_AUDIT_CORPUS_SCHEMA_VERSION}."
            )

        raw_cases = payload.get("cases")
        if not isinstance(raw_cases, list):
            raise ValueError("Reference audit corpus manifest must contain a cases[] array.")

        normalized_cases: list[dict[str, Any]] = []
        for index, raw_case in enumerate(raw_cases, start=1):
            if not isinstance(raw_case, dict):
                raise ValueError("Each reference audit corpus case must be a JSON object.")
            raw_audit_ids = (
                raw_case.get("audit_ids") if isinstance(raw_case.get("audit_ids"), dict) else {}
            )
            normalized_cases.append(
                {
                    "case_id": _coerce_text(raw_case.get("case_id")) or f"case-{index}",
                    "label": _coerce_text(raw_case.get("label")) or f"Case {index}",
                    "site_type": _coerce_text(raw_case.get("site_type")) or "unknown",
                    "description": _coerce_text(raw_case.get("description")),
                    "why_it_matters": _coerce_text(raw_case.get("why_it_matters")),
                    "target_name": _coerce_text(raw_case.get("target_name")),
                    "url": _coerce_text(raw_case.get("url")),
                    "audit_ids": {
                        tier: _safe_int(raw_audit_ids.get(tier))
                        for tier in REFERENCE_AUDIT_CORPUS_TIERS
                    },
                }
            )

        return {
            "schema_version": schema_version,
            "owner": _coerce_text(payload.get("owner")),
            "notes": _coerce_text(payload.get("notes")),
            "cases": normalized_cases,
        }

    def build_report(
        self,
        *,
        db: Session,
        days: int | None = 14,
        audit_ids: list[int] | None = None,
        requested_tiers: list[str] | None = None,
        manifest: dict[str, Any] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        normalized_audit_ids = sorted(
            {
                audit_id
                for audit_id in (_safe_int(item) for item in (audit_ids or ()))
                if audit_id is not None and audit_id > 0
            }
        )
        normalized_requested_tiers = sorted(
            {_coerce_text(item).lower() for item in (requested_tiers or ()) if _coerce_text(item)}
        )

        manifest_payload = manifest if isinstance(manifest, dict) else None
        if manifest_payload:
            for case in manifest_payload.get("cases", []):
                if not isinstance(case, dict):
                    continue
                raw_audit_ids = (
                    case.get("audit_ids") if isinstance(case.get("audit_ids"), dict) else {}
                )
                for tier in REFERENCE_AUDIT_CORPUS_TIERS:
                    manifest_audit_id = _safe_int(raw_audit_ids.get(tier))
                    if manifest_audit_id is not None and manifest_audit_id > 0:
                        normalized_audit_ids.append(manifest_audit_id)
            normalized_audit_ids = sorted(set(normalized_audit_ids))

        query = db.query(models.Audit)
        if normalized_audit_ids:
            query = query.filter(models.Audit.id.in_(normalized_audit_ids))
        elif days is not None and days > 0:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            query = query.filter(models.Audit.created_at >= cutoff_date)

        audits = query.order_by(models.Audit.created_at.desc(), models.Audit.id.desc()).all()

        audit_summaries: list[dict[str, Any]] = []

        trace_summary_by_audit_id = self._build_trace_summary_map(
            db=db,
            audit_ids=[audit.id for audit in audits],
        )

        for audit in audits:
            report = audit.full_report if isinstance(audit.full_report, dict) else {}
            debate = _extract_debate_payload(report)
            quality_gate = _extract_quality_gate(report)
            requested_tier = (
                _coerce_text(
                    quality_gate.get("requested_tier")
                    or debate.get("requested_tier")
                    or getattr(getattr(audit, "audit_type", None), "value", audit.audit_type)
                    or "unknown"
                ).lower()
                or "unknown"
            )

            if normalized_requested_tiers and requested_tier not in normalized_requested_tiers:
                continue

            pipeline_type = (
                _coerce_text(
                    quality_gate.get("pipeline_type")
                    or debate.get("pipeline_type")
                    or trace_summary_by_audit_id.get(audit.id, {}).get("pipeline_type")
                    or "unknown"
                )
                or "unknown"
            )
            violations = (
                quality_gate.get("violations")
                if isinstance(quality_gate.get("violations"), list)
                else []
            )
            violation_codes = [
                _coerce_text(item.get("code"))
                for item in violations
                if isinstance(item, dict) and _coerce_text(item.get("code"))
            ]
            trace_summary = trace_summary_by_audit_id.get(audit.id, {})
            trace_count = int(trace_summary.get("trace_count") or 0)

            missing_artifacts: list[str] = []
            if not quality_gate:
                missing_artifacts.append("quality_gate")
            if trace_count == 0:
                missing_artifacts.append("debate_trace")

            audit_summary = {
                "audit_id": audit.id,
                "created_at": _isoformat(audit.created_at),
                "requested_tier": requested_tier,
                "pipeline_type": pipeline_type,
                "target_name": _coerce_text(audit.target_name),
                "url": _coerce_text(audit.target_url or audit.url),
                "quality_gate_present": bool(quality_gate),
                "quality_gate_passed": (bool(quality_gate.get("passed")) if quality_gate else None),
                "violation_codes": violation_codes,
                "trace_count": trace_count,
                "trace_roles": trace_summary.get("trace_roles", []),
                "trace_statuses": trace_summary.get("trace_statuses", {}),
                "calibration_ready": bool(quality_gate) and trace_count > 0,
                "missing_artifacts": missing_artifacts,
                "suggested_prompt_files": _prompt_files_for_violation_codes(
                    pipeline_type=pipeline_type,
                    violation_codes=violation_codes,
                ),
            }
            audit_summaries.append(audit_summary)

        effective_limit = max(1, int(limit or 50))
        if normalized_audit_ids:
            effective_limit = max(effective_limit, len(normalized_audit_ids))

        audit_summaries = audit_summaries[:effective_limit]
        audit_lookup = {audit["audit_id"]: audit for audit in audit_summaries}
        violation_counter = Counter()
        for audit in audit_summaries:
            violation_counter.update(audit["violation_codes"])

        audits_with_quality_gate = sum(
            1 for audit in audit_summaries if audit["quality_gate_present"]
        )
        audits_failed = sum(1 for audit in audit_summaries if audit["quality_gate_passed"] is False)
        audits_with_traces = sum(1 for audit in audit_summaries if audit["trace_count"] > 0)
        calibration_ready_audits = sum(1 for audit in audit_summaries if audit["calibration_ready"])
        calibration_ready_failures = sum(
            1
            for audit in audit_summaries
            if audit["calibration_ready"] and audit["quality_gate_passed"] is False
        )

        report_payload = {
            "schema_version": PROMPT_QUALITY_CALIBRATION_REPORT_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "window_days": days,
            "filters": {
                "audit_ids": normalized_audit_ids,
                "requested_tiers": normalized_requested_tiers,
                "limit": effective_limit,
            },
            "summary": {
                "audits_considered": len(audit_summaries),
                "audits_with_quality_gate": audits_with_quality_gate,
                "audits_failed": audits_failed,
                "failure_rate": round(audits_failed / audits_with_quality_gate, 4)
                if audits_with_quality_gate
                else 0.0,
                "audits_with_traces": audits_with_traces,
                "calibration_ready_audits": calibration_ready_audits,
                "calibration_ready_failures": calibration_ready_failures,
            },
            "top_violations": [
                {"code": code, "count": count} for code, count in violation_counter.most_common(10)
            ],
            "audits": audit_summaries,
        }

        if manifest_payload:
            report_payload["reference_corpus"] = self._build_reference_corpus_summary(
                manifest=manifest_payload,
                audit_lookup=audit_lookup,
            )

        return report_payload

    def render_markdown(self, report: dict[str, Any]) -> str:
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        lines = [
            "# Orchestra V3 Prompt Quality Calibration Report",
            "",
            f"- Generated: {report.get('generated_at') or 'unknown'}",
            f"- Window days: {report.get('window_days') if report.get('window_days') is not None else 'custom'}",
            "",
            "## Summary",
            f"- Audits considered: {summary.get('audits_considered', 0)}",
            f"- Audits with quality gate: {summary.get('audits_with_quality_gate', 0)}",
            f"- Audits failed quality gate: {summary.get('audits_failed', 0)}",
            f"- Audits with debate traces: {summary.get('audits_with_traces', 0)}",
            f"- Calibration-ready audits: {summary.get('calibration_ready_audits', 0)}",
            f"- Calibration-ready failures: {summary.get('calibration_ready_failures', 0)}",
            "",
        ]

        top_violations = (
            report.get("top_violations") if isinstance(report.get("top_violations"), list) else []
        )
        if top_violations:
            lines.extend(
                [
                    "## Top Violations",
                    "",
                    "| Code | Count |",
                    "| --- | ---: |",
                ]
            )
            for violation in top_violations:
                if not isinstance(violation, dict):
                    continue
                lines.append(
                    f"| {violation.get('code') or 'unknown'} | {int(violation.get('count') or 0)} |"
                )
            lines.append("")

        reference_corpus = report.get("reference_corpus")
        if isinstance(reference_corpus, dict):
            corpus_summary = (
                reference_corpus.get("summary")
                if isinstance(reference_corpus.get("summary"), dict)
                else {}
            )
            lines.extend(
                [
                    "## Reference Corpus",
                    "",
                    f"- Cases defined: {corpus_summary.get('cases_total', 0)}",
                    f"- Cases with all three tiers assigned: {corpus_summary.get('cases_complete', 0)}",
                    f"- Cases ready for review: {corpus_summary.get('cases_ready_for_review', 0)}",
                    "",
                    "| Case | Status | Assigned tiers | Ready tiers | Failing tiers |",
                    "| --- | --- | --- | --- | --- |",
                ]
            )
            for case in reference_corpus.get("cases", []):
                if not isinstance(case, dict):
                    continue
                lines.append(
                    "| "
                    f"{case.get('label') or case.get('case_id') or 'unknown'} | "
                    f"{case.get('review_status') or 'unknown'} | "
                    f"{', '.join(case.get('assigned_tiers') or []) or '-'} | "
                    f"{', '.join(case.get('ready_tiers') or []) or '-'} | "
                    f"{', '.join(case.get('failing_tiers') or []) or '-'} |"
                )
            lines.append("")

        audits = report.get("audits") if isinstance(report.get("audits"), list) else []
        if audits:
            lines.extend(
                [
                    "## Audits",
                    "",
                    "| Audit | Tier | Pipeline | Gate | Traces | Missing artifacts | Suggested prompt files |",
                    "| --- | --- | --- | --- | ---: | --- | --- |",
                ]
            )
            for audit in audits:
                if not isinstance(audit, dict):
                    continue
                gate_value = audit.get("quality_gate_passed")
                gate_label = "missing"
                if gate_value is True:
                    gate_label = "pass"
                elif gate_value is False:
                    gate_label = "fail"

                lines.append(
                    "| "
                    f"{audit.get('audit_id') or 'unknown'} | "
                    f"{audit.get('requested_tier') or 'unknown'} | "
                    f"{audit.get('pipeline_type') or 'unknown'} | "
                    f"{gate_label} | "
                    f"{int(audit.get('trace_count') or 0)} | "
                    f"{', '.join(audit.get('missing_artifacts') or []) or '-'} | "
                    f"{', '.join(audit.get('suggested_prompt_files') or []) or '-'} |"
                )
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    def render_review_worksheet(self, report: dict[str, Any]) -> str:
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        reference_corpus = (
            report.get("reference_corpus")
            if isinstance(report.get("reference_corpus"), dict)
            else None
        )
        audits = report.get("audits") if isinstance(report.get("audits"), list) else []
        audit_lookup = {
            int(audit.get("audit_id")): audit
            for audit in audits
            if isinstance(audit, dict) and _safe_int(audit.get("audit_id")) is not None
        }

        lines = [
            "# Orchestra V3 Prompt Calibration Review Worksheet",
            "",
            f"- Generated: {report.get('generated_at') or 'unknown'}",
            f"- Audits considered: {summary.get('audits_considered', 0)}",
            f"- Calibration-ready audits: {summary.get('calibration_ready_audits', 0)}",
            "",
            "Use this worksheet for the human-only TASK-92 checks that the automated quality gate does not settle.",
            "",
        ]

        if reference_corpus:
            lines.extend(
                [
                    "## Reference Corpus Cases",
                    "",
                    "Mark the qualitative review outcome for each tier once you have inspected the debate traces.",
                    "",
                ]
            )
            for case in reference_corpus.get("cases", []):
                if not isinstance(case, dict):
                    continue
                lines.extend(
                    [
                        f"### {case.get('label') or case.get('case_id') or 'Case'}",
                        "",
                        f"- Review status: {case.get('review_status') or 'unknown'}",
                        f"- Assigned tiers: {', '.join(case.get('assigned_tiers') or []) or '-'}",
                        f"- Ready tiers: {', '.join(case.get('ready_tiers') or []) or '-'}",
                        "",
                    ]
                )
                tiers = case.get("tiers") if isinstance(case.get("tiers"), dict) else {}
                for tier in REFERENCE_AUDIT_CORPUS_TIERS:
                    tier_payload = tiers.get(tier) if isinstance(tiers.get(tier), dict) else {}
                    audit_id = _safe_int(tier_payload.get("audit_id"))
                    audit_summary = audit_lookup.get(audit_id or -1, {})
                    lines.extend(
                        self._render_audit_review_block(
                            audit_id=audit_id,
                            tier=tier,
                            pipeline_type=_coerce_text(audit_summary.get("pipeline_type"))
                            or "unknown",
                            violation_codes=list(
                                audit_summary.get("violation_codes")
                                or tier_payload.get("violation_codes")
                                or []
                            ),
                            suggested_prompt_files=list(
                                audit_summary.get("suggested_prompt_files") or []
                            ),
                            missing_artifacts=list(
                                audit_summary.get("missing_artifacts")
                                or tier_payload.get("missing_artifacts")
                                or []
                            ),
                        )
                    )
        else:
            lines.extend(["## Audit Reviews", ""])
            for audit in audits:
                if not isinstance(audit, dict):
                    continue
                lines.extend(
                    self._render_audit_review_block(
                        audit_id=_safe_int(audit.get("audit_id")),
                        tier=_coerce_text(audit.get("requested_tier")) or "unknown",
                        pipeline_type=_coerce_text(audit.get("pipeline_type")) or "unknown",
                        violation_codes=list(audit.get("violation_codes") or []),
                        suggested_prompt_files=list(audit.get("suggested_prompt_files") or []),
                        missing_artifacts=list(audit.get("missing_artifacts") or []),
                    )
                )

        return "\n".join(lines).rstrip() + "\n"

    def _render_audit_review_block(
        self,
        *,
        audit_id: int | None,
        tier: str,
        pipeline_type: str,
        violation_codes: list[str],
        suggested_prompt_files: list[str],
        missing_artifacts: list[str],
    ) -> list[str]:
        lines = [
            f"#### Tier: {tier}",
            "",
            f"- Audit ID: {audit_id if audit_id is not None else 'unassigned'}",
            f"- Pipeline: {pipeline_type or 'unknown'}",
            f"- Missing artifacts: {', '.join(missing_artifacts) or '-'}",
            f"- Violation codes: {', '.join(violation_codes) or '-'}",
            f"- Suggested prompt files: {', '.join(suggested_prompt_files) or '-'}",
            "",
            "- Review checklist:",
            "  - [ ] Recommendation specificity looks site-specific",
            "  - [ ] Critic behavior is directionally correct (not overly aggressive or overly permissive)",
            "  - [ ] Dedup/consolidation behavior looks acceptable for this audit",
            "  - [ ] Magistrate/manual-review behavior looks calibrated",
            "  - [ ] Cross-tier ordering still makes sense for this site",
            "- Reviewer notes:",
            "",
            "",
        ]
        return lines

    def _build_trace_summary_map(
        self,
        *,
        db: Session,
        audit_ids: list[int],
    ) -> dict[int, dict[str, Any]]:
        if not audit_ids:
            return {}

        traces = (
            db.query(models.DebateTrace)
            .filter(models.DebateTrace.audit_id.in_(audit_ids))
            .order_by(models.DebateTrace.audit_id.asc(), models.DebateTrace.created_at.asc())
            .all()
        )

        summary_by_audit_id: dict[int, dict[str, Any]] = {}
        for trace in traces:
            bucket = summary_by_audit_id.setdefault(
                trace.audit_id,
                {
                    "trace_count": 0,
                    "trace_roles": set(),
                    "trace_statuses": defaultdict(int),
                    "pipeline_type": _coerce_text(trace.pipeline_type) or "unknown",
                },
            )
            bucket["trace_count"] += 1
            bucket["trace_roles"].add(_coerce_text(trace.agent_role) or "unknown")
            status = _coerce_text(trace.status) or "unknown"
            bucket["trace_statuses"][status] += 1

        finalized: dict[int, dict[str, Any]] = {}
        for audit_id, bucket in summary_by_audit_id.items():
            finalized[audit_id] = {
                "trace_count": int(bucket["trace_count"]),
                "trace_roles": sorted(bucket["trace_roles"]),
                "trace_statuses": dict(sorted(bucket["trace_statuses"].items())),
                "pipeline_type": bucket["pipeline_type"],
            }
        return finalized

    def _build_reference_corpus_summary(
        self,
        *,
        manifest: dict[str, Any],
        audit_lookup: dict[int, dict[str, Any]],
    ) -> dict[str, Any]:
        cases_payload: list[dict[str, Any]] = []
        cases_complete = 0
        cases_ready_for_review = 0

        for case in manifest.get("cases", []):
            if not isinstance(case, dict):
                continue

            raw_audit_ids = case.get("audit_ids") if isinstance(case.get("audit_ids"), dict) else {}
            tier_payload: dict[str, dict[str, Any]] = {}
            assigned_tiers: list[str] = []
            ready_tiers: list[str] = []
            failing_tiers: list[str] = []
            missing_tiers: list[str] = []

            for tier in REFERENCE_AUDIT_CORPUS_TIERS:
                audit_id = _safe_int(raw_audit_ids.get(tier))
                audit_summary = audit_lookup.get(audit_id) if audit_id is not None else None

                if audit_id is None:
                    status = "missing_audit_id"
                    missing_tiers.append(tier)
                elif audit_summary is None:
                    status = "audit_not_found"
                    missing_tiers.append(tier)
                    assigned_tiers.append(tier)
                else:
                    assigned_tiers.append(tier)
                    if audit_summary["calibration_ready"]:
                        status = "ready"
                        ready_tiers.append(tier)
                    else:
                        status = "needs_artifacts"
                    if audit_summary["quality_gate_passed"] is False:
                        failing_tiers.append(tier)

                tier_payload[tier] = {
                    "audit_id": audit_id,
                    "status": status,
                    "quality_gate_passed": (
                        audit_summary.get("quality_gate_passed")
                        if isinstance(audit_summary, dict)
                        else None
                    ),
                    "missing_artifacts": (
                        list(audit_summary.get("missing_artifacts") or [])
                        if isinstance(audit_summary, dict)
                        else []
                    ),
                    "violation_codes": (
                        list(audit_summary.get("violation_codes") or [])
                        if isinstance(audit_summary, dict)
                        else []
                    ),
                }

            case_complete = len(assigned_tiers) == len(REFERENCE_AUDIT_CORPUS_TIERS)
            case_ready_for_review = len(ready_tiers) == len(REFERENCE_AUDIT_CORPUS_TIERS)
            if case_complete:
                cases_complete += 1
            if case_ready_for_review:
                cases_ready_for_review += 1

            review_status = "incomplete"
            if case_complete and case_ready_for_review:
                review_status = "ready_for_review"
            elif case_complete and ready_tiers:
                review_status = "partial_artifacts"

            cases_payload.append(
                {
                    "case_id": case.get("case_id"),
                    "label": case.get("label"),
                    "site_type": case.get("site_type"),
                    "target_name": case.get("target_name"),
                    "url": case.get("url"),
                    "review_status": review_status,
                    "assigned_tiers": assigned_tiers,
                    "ready_tiers": ready_tiers,
                    "failing_tiers": failing_tiers,
                    "missing_tiers": missing_tiers,
                    "tiers": tier_payload,
                }
            )

        return {
            "schema_version": manifest.get("schema_version"),
            "owner": manifest.get("owner"),
            "notes": manifest.get("notes"),
            "summary": {
                "cases_total": len(cases_payload),
                "cases_complete": cases_complete,
                "cases_ready_for_review": cases_ready_for_review,
            },
            "cases": cases_payload,
        }


prompt_quality_calibration_service = PromptQualityCalibrationService()
