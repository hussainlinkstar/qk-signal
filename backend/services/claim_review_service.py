from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session, selectinload

import models
from schemas.claim_reviews import (
    ClaimReviewDecisionResponse,
    ClaimReviewImpactResponse,
    ClaimReviewQueueItemResponse,
    ClaimReviewQueueResponse,
    ClaimReviewSummaryResponse,
)


REVIEW_PENDING_DISPOSITION = "needs_manual_review"
REVIEW_APPROVED_DISPOSITION = "manually_approved"
REVIEW_REFUSED_DISPOSITION = "manually_refused"
REVIEWABLE_DISPOSITIONS = {
    REVIEW_PENDING_DISPOSITION,
    REVIEW_APPROVED_DISPOSITION,
    REVIEW_REFUSED_DISPOSITION,
}
WRITE_ROLES = {
    models.WorkspaceRole.ADMIN.value,
    models.WorkspaceRole.MANAGER.value,
    models.WorkspaceRole.EDITOR.value,
}
_KNOWN_REVIEW_DOMAINS = {"seo", "geo", "aeo", "general", "mixed"}


@dataclass(frozen=True)
class ReviewableClaim:
    claim_id: str
    claim_domain: str
    claim_text: str
    claim_payload: dict[str, Any]
    current_disposition: str


def _normalize_text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _isoformat(value: datetime | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.astimezone(timezone.utc).isoformat()


def _user_display_name(user: models.User | None) -> str | None:
    if user is None:
        return None
    candidate = _normalize_text(getattr(user, "company_name", None))
    if candidate:
        return candidate
    email = _normalize_text(getattr(user, "email", None))
    if email and "@" in email:
        return email.split("@", 1)[0]
    return email


def _derive_claim_domain(claim: dict[str, Any], *, claim_id: str | None = None) -> str:
    domain = _normalize_text(claim.get("domain"))
    if domain:
        lowered = domain.lower()
        if lowered in _KNOWN_REVIEW_DOMAINS:
            return lowered
    resolved_claim_id = _normalize_text(claim_id) or _normalize_text(claim.get("claim_id"))
    prefix = (resolved_claim_id or "").split("-", 1)[0].split("_", 1)[0].lower()
    if prefix.startswith("seo"):
        return "seo"
    if prefix.startswith("geo"):
        return "geo"
    if prefix.startswith("aeo"):
        return "aeo"
    return "general"


def _resolve_debate_metadata(report: dict[str, Any]) -> dict[str, Any]:
    debate = report.get("debate")
    if isinstance(debate, dict):
        return debate
    metadata = report.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("debate"), dict):
        return metadata.get("debate")
    return {}


def _build_evidence_anchor_excerpt(report: dict[str, Any]) -> dict[str, Any] | None:
    debate_metadata = _resolve_debate_metadata(report)
    evidence_anchor = debate_metadata.get("evidence_anchor")
    if not isinstance(evidence_anchor, dict):
        return None

    excerpt: dict[str, Any] = {}
    scores = evidence_anchor.get("scores")
    if isinstance(scores, dict):
        excerpt["scores"] = {
            key: value
            for key, value in scores.items()
            if key in {"seo", "geo", "aeo", "overall"} and isinstance(value, (int, float))
        }

    critical_metrics = evidence_anchor.get("critical_metrics")
    if isinstance(critical_metrics, dict):
        excerpt["critical_metrics"] = {
            key: value
            for key, value in critical_metrics.items()
            if isinstance(value, (int, float, str, bool))
            or (isinstance(value, list) and len(value) <= 5)
        }

    scan_timestamp = _normalize_text(evidence_anchor.get("scan_timestamp"))
    if scan_timestamp:
        excerpt["scan_timestamp"] = scan_timestamp

    return excerpt or evidence_anchor


def _extract_reviewable_claims(report: dict[str, Any]) -> list[ReviewableClaim]:
    metadata = report.get("metadata") if isinstance(report.get("metadata"), dict) else {}
    dual_track_shadow = (
        metadata.get("dual_track_shadow")
        if isinstance(metadata.get("dual_track_shadow"), dict)
        else {}
    )
    raw_claims = dual_track_shadow.get("claims")
    if not isinstance(raw_claims, list):
        return []

    claims: list[ReviewableClaim] = []
    for item in raw_claims:
        if not isinstance(item, dict):
            continue
        track = (_normalize_text(item.get("track")) or "").lower()
        if track != "track_b":
            continue
        claim_id = _normalize_text(item.get("claim_id"))
        claim_text = _normalize_text(item.get("claim_text"))
        disposition = (_normalize_text(item.get("shadow_disposition")) or "").lower()
        if not claim_id or not claim_text or disposition not in REVIEWABLE_DISPOSITIONS:
            continue
        claims.append(
            ReviewableClaim(
                claim_id=claim_id,
                claim_domain=_derive_claim_domain(item, claim_id=claim_id),
                claim_text=claim_text,
                claim_payload=item,
                current_disposition=disposition,
            )
        )
    return claims


def _review_summary_from_claims(
    *,
    audit_id: int,
    claims: list[ReviewableClaim],
) -> ClaimReviewSummaryResponse:
    approved_count = sum(
        1 for claim in claims if claim.current_disposition == REVIEW_APPROVED_DISPOSITION
    )
    refused_count = sum(
        1 for claim in claims if claim.current_disposition == REVIEW_REFUSED_DISPOSITION
    )
    pending_count = sum(
        1 for claim in claims if claim.current_disposition == REVIEW_PENDING_DISPOSITION
    )
    return ClaimReviewSummaryResponse(
        audit_id=audit_id,
        total_flagged=len(claims),
        approved_count=approved_count,
        refused_count=refused_count,
        pending_count=pending_count,
        impact=ClaimReviewImpactResponse(
            score_recalculated=False,
            export_excluded_claims=refused_count,
            note=(
                "Refused claims are excluded from export-safe integrity summaries; audit scores are not "
                "recalculated automatically."
            ),
        ),
    )


class ClaimReviewService:
    def _get_decision_rows(
        self,
        *,
        db: Session,
        audit_id: int,
    ) -> list[models.ClaimReviewDecision]:
        return (
            db.query(models.ClaimReviewDecision)
            .options(selectinload(models.ClaimReviewDecision.reviewed_by))
            .filter(models.ClaimReviewDecision.audit_id == audit_id)
            .order_by(
                models.ClaimReviewDecision.reviewed_at.desc(), models.ClaimReviewDecision.id.desc()
            )
            .all()
        )

    def _serialize_decision(
        self,
        decision: models.ClaimReviewDecision,
    ) -> ClaimReviewDecisionResponse:
        return ClaimReviewDecisionResponse(
            id=decision.id,
            audit_id=decision.audit_id,
            project_id=decision.project_id,
            claim_id=decision.claim_id,
            claim_domain=str(decision.claim_domain or "").strip() or "general",
            claim_text=str(decision.claim_text or "").strip(),
            original_disposition=str(decision.original_disposition or "").strip()
            or REVIEW_PENDING_DISPOSITION,
            review_disposition=str(decision.review_disposition or "").strip(),
            review_note=_normalize_text(decision.review_note),
            reviewed_by_id=decision.reviewed_by_id,
            reviewed_by_display_name=_user_display_name(decision.reviewed_by),
            reviewed_at=_isoformat(decision.reviewed_at),
            schema_version=str(decision.schema_version or "1"),
        )

    def _sync_signal_claim_disposition_facts(
        self,
        *,
        db: Session,
        audit: models.Audit,
        claims: list[ReviewableClaim],
    ) -> None:
        rows = (
            db.query(models.SignalClaimDispositionFact)
            .filter(models.SignalClaimDispositionFact.audit_id == audit.id)
            .all()
        )
        if not rows:
            return

        pending_by_domain: dict[str, int] = {}
        approved_by_domain: dict[str, int] = {}
        refused_by_domain: dict[str, int] = {}
        for claim in claims:
            domain = claim.claim_domain
            if claim.current_disposition == REVIEW_PENDING_DISPOSITION:
                pending_by_domain[domain] = pending_by_domain.get(domain, 0) + 1
            elif claim.current_disposition == REVIEW_APPROVED_DISPOSITION:
                approved_by_domain[domain] = approved_by_domain.get(domain, 0) + 1
            elif claim.current_disposition == REVIEW_REFUSED_DISPOSITION:
                refused_by_domain[domain] = refused_by_domain.get(domain, 0) + 1

        row_by_domain = {str(row.domain or "").strip().lower(): row for row in rows}
        mixed_row = row_by_domain.get("mixed")

        def _resolve_row(domain: str) -> models.SignalClaimDispositionFact | None:
            direct = row_by_domain.get(domain)
            if direct is not None:
                return direct
            if domain == "general":
                return mixed_row
            return mixed_row if len(row_by_domain) == 1 else None

        touched: set[int] = set()
        for domain in set(pending_by_domain) | set(approved_by_domain) | set(refused_by_domain):
            row = _resolve_row(domain)
            if row is None:
                continue
            row.claims_needs_manual_review = int(pending_by_domain.get(domain, 0))
            row.claims_manually_approved = int(approved_by_domain.get(domain, 0))
            row.claims_manually_refused = int(refused_by_domain.get(domain, 0))
            touched.add(row.id)

        for row in rows:
            if row.id in touched:
                continue
            row.claims_needs_manual_review = 0
            row.claims_manually_approved = 0
            row.claims_manually_refused = 0

    def get_review_queue(
        self,
        *,
        db: Session,
        audit: models.Audit,
        can_review: bool,
    ) -> ClaimReviewQueueResponse:
        report = audit.full_report if isinstance(audit.full_report, dict) else {}
        claims = _extract_reviewable_claims(report)
        decisions_by_claim_id = {
            decision.claim_id: decision
            for decision in self._get_decision_rows(db=db, audit_id=audit.id)
        }
        evidence_anchor_excerpt = _build_evidence_anchor_excerpt(report)

        items: list[ClaimReviewQueueItemResponse] = []
        for claim in claims:
            decision = decisions_by_claim_id.get(claim.claim_id)
            critique_reference = _normalize_text(
                claim.claim_payload.get("explanation")
            ) or _normalize_text(claim.claim_payload.get("judge_resolution"))
            items.append(
                ClaimReviewQueueItemResponse(
                    claim_id=claim.claim_id,
                    domain=claim.claim_domain,
                    claim_text=claim.claim_text,
                    current_disposition=claim.current_disposition,
                    confidence_score=_safe_float(claim.claim_payload.get("certainty_score")),
                    confidence_band=_normalize_text(claim.claim_payload.get("confidence_band")),
                    critique_reference=critique_reference,
                    evidence_anchor_excerpt=evidence_anchor_excerpt,
                    reason_codes=[
                        str(code).strip().lower()
                        for code in claim.claim_payload.get("reason_codes", [])
                        if str(code).strip()
                    ]
                    if isinstance(claim.claim_payload.get("reason_codes"), list)
                    else [],
                    problem_refs=[
                        str(code).strip()
                        for code in claim.claim_payload.get("problem_refs", [])
                        if str(code).strip()
                    ]
                    if isinstance(claim.claim_payload.get("problem_refs"), list)
                    else [],
                    evidence_refs=[
                        str(code).strip()
                        for code in claim.claim_payload.get("evidence_refs", [])
                        if str(code).strip()
                    ]
                    if isinstance(claim.claim_payload.get("evidence_refs"), list)
                    else [],
                    suggested_rewrite=_normalize_text(claim.claim_payload.get("suggested_rewrite")),
                    review_decision=self._serialize_decision(decision)
                    if decision is not None
                    else None,
                )
            )

        items.sort(
            key=lambda item: (
                item.current_disposition != REVIEW_PENDING_DISPOSITION,
                item.domain,
                item.claim_id,
            )
        )
        summary = _review_summary_from_claims(audit_id=audit.id, claims=claims)
        return ClaimReviewQueueResponse(
            audit_id=audit.id,
            total_flagged=summary.total_flagged,
            reviewed=summary.approved_count + summary.refused_count,
            approved_count=summary.approved_count,
            refused_count=summary.refused_count,
            pending=summary.pending_count,
            can_review=can_review,
            claims=items,
        )

    def get_review_summary(
        self,
        *,
        db: Session,
        audit: models.Audit,
    ) -> ClaimReviewSummaryResponse:
        report = audit.full_report if isinstance(audit.full_report, dict) else {}
        claims = _extract_reviewable_claims(report)
        return _review_summary_from_claims(audit_id=audit.id, claims=claims)

    def apply_reviews_to_report(
        self,
        *,
        db: Session,
        audit: models.Audit,
    ) -> dict[str, Any]:
        report = deepcopy(audit.full_report if isinstance(audit.full_report, dict) else {})
        metadata = report.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
            report["metadata"] = metadata

        dual_track_shadow = metadata.setdefault("dual_track_shadow", {})
        if not isinstance(dual_track_shadow, dict):
            dual_track_shadow = {}
            metadata["dual_track_shadow"] = dual_track_shadow

        raw_claims = dual_track_shadow.get("claims")
        if not isinstance(raw_claims, list):
            raw_claims = []
            dual_track_shadow["claims"] = raw_claims

        decisions_by_claim_id = {
            decision.claim_id: decision
            for decision in self._get_decision_rows(db=db, audit_id=audit.id)
        }

        reviewable_claims: list[ReviewableClaim] = []
        for item in raw_claims:
            if not isinstance(item, dict):
                continue
            track = (_normalize_text(item.get("track")) or "").lower()
            if track != "track_b":
                continue
            claim_id = _normalize_text(item.get("claim_id"))
            claim_text = _normalize_text(item.get("claim_text"))
            if not claim_id or not claim_text:
                continue

            decision = decisions_by_claim_id.get(claim_id)
            disposition = (_normalize_text(item.get("shadow_disposition")) or "").lower()
            if decision is not None:
                disposition = str(decision.review_disposition or "").strip().lower() or disposition
                item["shadow_disposition"] = disposition
                item["review_decision"] = {
                    "disposition": disposition,
                    "note": _normalize_text(decision.review_note),
                    "reviewed_at": _isoformat(decision.reviewed_at),
                    "reviewed_by_id": decision.reviewed_by_id,
                    "reviewed_by_display_name": _user_display_name(decision.reviewed_by),
                }
            elif disposition in {REVIEW_APPROVED_DISPOSITION, REVIEW_REFUSED_DISPOSITION}:
                # If the report already carries manual state but the decision row is missing, keep the audit trail.
                item["review_decision"] = item.get("review_decision")

            if disposition in REVIEWABLE_DISPOSITIONS:
                reviewable_claims.append(
                    ReviewableClaim(
                        claim_id=claim_id,
                        claim_domain=_derive_claim_domain(item, claim_id=claim_id),
                        claim_text=claim_text,
                        claim_payload=item,
                        current_disposition=disposition,
                    )
                )

        total_track_b_claims = 0
        track_b_active_claims = 0
        track_b_supported = 0
        track_b_flagged = 0
        track_b_needs_manual_review = 0
        track_b_omitted = 0
        track_b_manually_approved = 0
        track_b_manually_refused = 0
        supported_claims = 0
        flagged_claims = 0
        omitted_claims = 0
        needs_manual_review_claims = 0
        mixed_claims = 0
        track_a_claims = 0

        for item in raw_claims:
            if not isinstance(item, dict):
                continue
            track = (_normalize_text(item.get("track")) or "").lower()
            disposition = (_normalize_text(item.get("shadow_disposition")) or "").lower()
            if track == "track_a":
                track_a_claims += 1
            elif track == "mixed":
                mixed_claims += 1
            elif track == "track_b":
                total_track_b_claims += 1

            if disposition in {"supported", REVIEW_APPROVED_DISPOSITION}:
                supported_claims += 1
            elif disposition == "flagged":
                flagged_claims += 1
            elif disposition == "omitted":
                omitted_claims += 1
            elif disposition == REVIEW_PENDING_DISPOSITION:
                needs_manual_review_claims += 1

            if track != "track_b":
                continue
            if disposition == REVIEW_REFUSED_DISPOSITION:
                track_b_manually_refused += 1
                continue

            track_b_active_claims += 1
            if disposition in {"supported", REVIEW_APPROVED_DISPOSITION}:
                track_b_supported += 1
                if disposition == REVIEW_APPROVED_DISPOSITION:
                    track_b_manually_approved += 1
            elif disposition == "flagged":
                track_b_flagged += 1
            elif disposition == REVIEW_PENDING_DISPOSITION:
                track_b_needs_manual_review += 1
            elif disposition == "omitted":
                track_b_omitted += 1

        shadow_summary = dual_track_shadow.get("summary")
        if not isinstance(shadow_summary, dict):
            shadow_summary = {}
        shadow_summary.update(
            {
                "track_a_claims": track_a_claims,
                "track_b_claims": total_track_b_claims,
                "mixed_claims": mixed_claims,
                "supported_claims": supported_claims,
                "flagged_claims": flagged_claims,
                "needs_manual_review_claims": needs_manual_review_claims,
                "omitted_claims": omitted_claims,
                "manually_approved_claims": track_b_manually_approved,
                "manually_refused_claims": track_b_manually_refused,
            }
        )
        dual_track_shadow["summary"] = shadow_summary

        track_b_judge = dual_track_shadow.get("track_b_judge")
        if isinstance(track_b_judge, dict):
            track_b_judge["needs_manual_review_claims"] = track_b_needs_manual_review

        integrity_certificate = report.get("integrity_certificate")
        if not isinstance(integrity_certificate, dict):
            integrity_certificate = {}
        certificate_summary = integrity_certificate.get("summary")
        if not isinstance(certificate_summary, dict):
            certificate_summary = {}
        certificate_summary.update(
            {
                "track_b_total": track_b_active_claims,
                "track_b_supported": track_b_supported,
                "track_b_flagged": track_b_flagged,
                "track_b_needs_manual_review": track_b_needs_manual_review,
                "track_b_omitted": track_b_omitted,
                "track_b_manually_approved": track_b_manually_approved,
                "track_b_manually_refused": track_b_manually_refused,
                "total_claims": track_a_claims + track_b_active_claims,
            }
        )
        integrity_certificate["summary"] = certificate_summary
        report["integrity_certificate"] = integrity_certificate

        metadata["track_b_claim_count"] = track_b_active_claims
        integrity_certificate_summary = metadata.get("integrity_certificate_summary")
        if not isinstance(integrity_certificate_summary, dict):
            integrity_certificate_summary = {}
        integrity_certificate_summary.update(
            {
                "track_b_claim_count": track_b_active_claims,
                "needs_manual_review_claims": track_b_needs_manual_review,
                "manually_approved_claims": track_b_manually_approved,
                "manually_refused_claims": track_b_manually_refused,
            }
        )
        metadata["integrity_certificate_summary"] = integrity_certificate_summary

        audit.full_report = report
        self._sync_signal_claim_disposition_facts(db=db, audit=audit, claims=reviewable_claims)
        return report

    def submit_review(
        self,
        *,
        db: Session,
        audit: models.Audit,
        claim_id: str,
        disposition: str,
        note: str | None,
        reviewer: models.User,
    ) -> ClaimReviewDecisionResponse:
        normalized_disposition = str(disposition or "").strip().lower()
        if normalized_disposition not in {REVIEW_APPROVED_DISPOSITION, REVIEW_REFUSED_DISPOSITION}:
            raise HTTPException(status_code=400, detail="Unsupported review disposition.")

        report = audit.full_report if isinstance(audit.full_report, dict) else {}
        claims = _extract_reviewable_claims(report)
        claim = next((item for item in claims if item.claim_id == claim_id), None)
        if claim is None:
            raise HTTPException(status_code=404, detail="Claim review target not found.")
        if audit.project_id is None:
            raise HTTPException(
                status_code=400, detail="Audit is not linked to a workspace project."
            )

        existing = (
            db.query(models.ClaimReviewDecision)
            .filter(
                models.ClaimReviewDecision.audit_id == audit.id,
                models.ClaimReviewDecision.claim_id == claim.claim_id,
            )
            .first()
        )
        reviewed_at = datetime.now(timezone.utc)
        if existing is None:
            decision = models.ClaimReviewDecision(
                audit_id=audit.id,
                project_id=audit.project_id,
                claim_id=claim.claim_id,
                claim_domain=claim.claim_domain,
                claim_text=claim.claim_text,
                original_disposition=REVIEW_PENDING_DISPOSITION,
                review_disposition=normalized_disposition,
                review_note=note,
                reviewed_by_id=reviewer.id,
                reviewed_at=reviewed_at,
            )
            db.add(decision)
            db.flush()
        else:
            existing.claim_domain = claim.claim_domain
            existing.claim_text = claim.claim_text
            existing.original_disposition = REVIEW_PENDING_DISPOSITION
            existing.review_disposition = normalized_disposition
            existing.review_note = note
            existing.reviewed_by_id = reviewer.id
            existing.reviewed_at = reviewed_at
            decision = existing
            db.flush()

        self.apply_reviews_to_report(db=db, audit=audit)
        db.flush()
        refreshed = (
            db.query(models.ClaimReviewDecision)
            .options(selectinload(models.ClaimReviewDecision.reviewed_by))
            .filter(models.ClaimReviewDecision.id == decision.id)
            .one()
        )
        return self._serialize_decision(refreshed)


claim_review_service = ClaimReviewService()
