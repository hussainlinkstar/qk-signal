"""Public tokenized endpoints for post-trial feedback collection."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from services.trial_feedback_service import (
    get_feedback_request_by_token,
    serialize_public_feedback_request,
    submit_feedback,
)

router = APIRouter(prefix="/trial-feedback", tags=["trial-feedback"])


class TrialFeedbackPublicResponse(BaseModel):
    token: str
    status: str
    recipient_email: str
    recipient_name: str
    requested_by_name: str
    trigger_reason: str
    trial_started_at: str | None = None
    trial_ended_at: str | None = None
    expires_at: str | None = None
    submitted_at: str | None = None


class SubmitTrialFeedbackRequest(BaseModel):
    overall_rating: int = Field(ge=1, le=5)
    would_recommend: Literal["yes", "maybe", "no"]
    what_worked_well: str | None = Field(default=None, max_length=4000)
    what_was_missing: str | None = Field(default=None, max_length=4000)
    improvement_suggestions: str | None = Field(default=None, max_length=4000)


class SubmitTrialFeedbackResponse(BaseModel):
    status: str
    submitted_at: str | None = None


@router.get("/{token}", response_model=TrialFeedbackPublicResponse)
def get_trial_feedback_request(
    token: str,
    _x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
) -> Any:
    feedback_request = get_feedback_request_by_token(db, token)
    if feedback_request is None:
        raise HTTPException(status_code=404, detail="Feedback request not found.")
    db.commit()
    return serialize_public_feedback_request(db, feedback_request)


@router.post("/{token}/submit", response_model=SubmitTrialFeedbackResponse)
def submit_trial_feedback(
    token: str,
    payload: SubmitTrialFeedbackRequest,
    _x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    db: Session = Depends(get_db),
) -> Any:
    feedback_request = submit_feedback(
        db,
        token=token,
        overall_rating=payload.overall_rating,
        would_recommend=payload.would_recommend,
        what_worked_well=payload.what_worked_well,
        what_was_missing=payload.what_was_missing,
        improvement_suggestions=payload.improvement_suggestions,
    )
    db.commit()
    return {
        "status": feedback_request.status,
        "submitted_at": (
            feedback_request.submitted_at.isoformat() if feedback_request.submitted_at else None
        ),
    }
