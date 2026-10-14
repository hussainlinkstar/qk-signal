from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


MAX_REVIEW_NOTE_LENGTH = 500


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


class ClaimReviewRequest(BaseModel):
    disposition: Literal["manually_approved", "manually_refused"]
    note: str | None = Field(default=None, max_length=MAX_REVIEW_NOTE_LENGTH)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        normalized = _normalize_optional_text(value)
        if normalized is None:
            return None
        if len(normalized) > MAX_REVIEW_NOTE_LENGTH:
            raise ValueError(f"Review note must be {MAX_REVIEW_NOTE_LENGTH} characters or fewer.")
        return normalized


class ClaimReviewDecisionResponse(BaseModel):
    id: int
    audit_id: int
    project_id: int
    claim_id: str
    claim_domain: str
    claim_text: str
    original_disposition: str
    review_disposition: str
    review_note: str | None = None
    reviewed_by_id: int | None = None
    reviewed_by_display_name: str | None = None
    reviewed_at: str
    schema_version: str = "1"


class ClaimReviewQueueItemResponse(BaseModel):
    claim_id: str
    domain: str
    claim_text: str
    current_disposition: str
    confidence_score: float | None = None
    confidence_band: str | None = None
    critique_reference: str | None = None
    evidence_anchor_excerpt: dict[str, Any] | None = None
    reason_codes: list[str] = Field(default_factory=list)
    problem_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    suggested_rewrite: str | None = None
    review_decision: ClaimReviewDecisionResponse | None = None


class ClaimReviewQueueResponse(BaseModel):
    audit_id: int
    total_flagged: int
    reviewed: int
    approved_count: int
    refused_count: int
    pending: int
    can_review: bool = False
    claims: list[ClaimReviewQueueItemResponse] = Field(default_factory=list)


class ClaimReviewImpactResponse(BaseModel):
    score_recalculated: bool = False
    export_excluded_claims: int = 0
    note: str


class ClaimReviewSummaryResponse(BaseModel):
    audit_id: int
    total_flagged: int
    approved_count: int
    refused_count: int
    pending_count: int
    impact: ClaimReviewImpactResponse
