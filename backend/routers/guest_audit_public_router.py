"""Public guest audit API consumed by the marketing site.

The marketing site owns ``/signal/guest-audit`` and had no API integration at
all, so this is a new contract rather than a change to an existing one:

    POST /api/v1/public/guest-audit        -> 202 { job_id, status, poll_url }
    GET  /api/v1/public/guest-audit/{id}   -> 200 { job_id, status, ... }

It is submit plus poll because an audit takes tens of seconds, which is longer
than the edge proxy will hold a connection open; a single blocking call has
been seen returning 502 while the audit completed and was paid for. Signal's
own legacy synchronous ``POST /api/v1/guest-audit`` is untouched.

Cross-origin access follows SIGNAL-1040: scoped to this path, uncredentialed,
origins from ``PUBLIC_SITE_ORIGINS``. Those are deliberately not added to
``CORS_ORIGINS``, which is credentialed and global, because that would make an
XSS on the marketing site a cookie-bearing pivot into all of Signal. The
headers themselves are attached by ``middleware/public_site_cors.py`` rather
than per route, so a 400 or a 429 is readable by the site too: a rejected
request without CORS headers is an opaque network error in the browser and
the visitor would see nothing at all.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from database import get_db
from services.guest_audit_public import (
    STATUS_QUEUED,
    build_status_payload,
    build_target_fingerprint,
    create_job,
    enforce_public_guest_audit_rate_limit,
    find_job_for_target,
    new_job_id,
    read_job,
    resolve_job_ttl_seconds,
    resolve_poll_interval_ms,
)
from services.url_validation import normalize_and_validate_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/public", tags=["Guest Audit (Public)"])

# One generic message for every rejected target. A private address, an
# unresolvable host and a malformed string are indistinguishable to the
# caller, so the endpoint cannot be used to probe Signal's internal network.
INVALID_TARGET_DETAIL = "Invalid URL. Please provide a public http:// or https:// address."


class PublicGuestAuditRequest(BaseModel):
    # A public body is strict: an unknown key is a client bug or an attempt to
    # reach a field this endpoint does not offer, and both should be loud.
    model_config = ConfigDict(extra="forbid")

    audit_target_type: Literal["website", "brand"] = "website"
    url: str | None = None
    target_name: str | None = Field(default=None, min_length=1, max_length=256)
    target_metadata: dict[str, Any] | None = None
    email: EmailStr | None = None

    @field_validator("url", mode="before")
    @classmethod
    def validate_url(cls, value: Any) -> str | None:
        if value is None:
            return None
        raw = str(value).strip()
        if not raw:
            return None
        try:
            return normalize_and_validate_url(raw)
        except ValueError as exc:
            raise ValueError(INVALID_TARGET_DETAIL) from exc

    @field_validator("target_name", mode="before")
    @classmethod
    def normalize_target_name(cls, value: Any) -> str | None:
        if value is None:
            return None
        return str(value).strip() or None

    @model_validator(mode="after")
    def validate_target(self) -> "PublicGuestAuditRequest":
        if self.audit_target_type == "website" and not self.url:
            raise ValueError("Website audits require a url.")
        if self.audit_target_type == "brand" and not self.target_name:
            raise ValueError("Brand audits require a target_name.")
        if self.target_metadata is not None and len(self.target_metadata) > 20:
            raise ValueError("target_metadata accepts at most 20 keys.")
        return self


@router.post("/guest-audit", status_code=status.HTTP_202_ACCEPTED)
async def submit_public_guest_audit(
    payload: PublicGuestAuditRequest,
    http_request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Queue a guest audit and return a job to poll.

    Never runs the audit inline: the work is pushed onto the guest audit queue
    and executed by the audit worker.
    """
    _ = db, response
    await enforce_public_guest_audit_rate_limit(http_request)

    fingerprint = build_target_fingerprint(
        audit_target_type=payload.audit_target_type,
        target_url=payload.url,
        target_name=payload.target_name,
    )

    existing_job_id = await find_job_for_target(fingerprint)
    if existing_job_id:
        # The same target is already being audited, so join that job instead
        # of paying for the identical run twice.
        return _accepted_payload(existing_job_id, deduplicated=True)

    job_id = new_job_id()
    client_ip = _client_ip(http_request)
    user_agent = http_request.headers.get("user-agent", "")

    try:
        await create_job(
            job_id=job_id,
            audit_target_type=payload.audit_target_type,
            target_url=payload.url,
            target_name=payload.target_name,
            target_metadata=payload.target_metadata,
            email=str(payload.email) if payload.email else None,
            ip_hash=hashlib.sha256(client_ip.encode("utf-8")).hexdigest(),
            user_agent_hash=(
                hashlib.sha256(user_agent.encode("utf-8")).hexdigest() if user_agent else None
            ),
            referrer=http_request.headers.get("referer"),
            request_id=getattr(http_request.state, "request_id", None),
            target_fingerprint=fingerprint,
        )
    except RuntimeError:
        raise HTTPException(
            status_code=503,
            detail="Free audits are busy right now. Please try again in a few minutes.",
            headers={"Retry-After": "60"},
        ) from None
    except Exception as exc:
        logger.warning("Guest audit job could not be queued: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Free audits are temporarily unavailable. Please try again shortly.",
            headers={"Retry-After": "60"},
        ) from None

    return _accepted_payload(job_id, deduplicated=False)


@router.get("/guest-audit/{job_id}")
async def get_public_guest_audit(job_id: str, http_request: Request, response: Response):
    """Report job progress, and the allowlisted result once it is done."""
    _ = http_request
    response.headers["Cache-Control"] = "no-store"

    try:
        record = await read_job(job_id)
    except Exception as exc:
        logger.warning("Guest audit job lookup failed for %s: %s", job_id, exc)
        raise HTTPException(
            status_code=503,
            detail="Audit status is temporarily unavailable. Please retry.",
            headers={"Retry-After": "5"},
        ) from None

    if not record:
        # Unknown id and expired job are the same answer, so a job id cannot
        # be probed for existence after it has aged out.
        raise HTTPException(
            status_code=404,
            detail="This audit is no longer available. Please run a new one.",
        )

    return build_status_payload(job_id, record)


def _accepted_payload(job_id: str, *, deduplicated: bool) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "status": STATUS_QUEUED,
        "poll_url": f"/api/v1/public/guest-audit/{job_id}",
        "poll_after_ms": resolve_poll_interval_ms(),
        "expires_in_seconds": resolve_job_ttl_seconds(),
        "deduplicated": deduplicated,
    }


def _client_ip(request: Request) -> str:
    from routers.api_router import _resolve_client_ip

    return _resolve_client_ip(request)
