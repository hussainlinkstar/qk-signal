import asyncio
import logging
import socket
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, HttpUrl, field_validator
from sqlalchemy.orm import Session

from app.i18n import translate_backend_message
from core.config import settings
from database import get_db
from services.email_sender import send as send_email

router = APIRouter(tags=["Contact"])
logger = logging.getLogger(__name__)

DEFAULT_SUPPORT_INBOX = "support@qiko.ai"
DEFAULT_BILLING_INBOX = "billing@qiko.ai"
DEFAULT_PRIVACY_INBOX = "privacy@qiko.ai"
DEFAULT_TICKET_PREFIX = "STX"


class ContactMessageRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    company: str | None = Field(default=None, max_length=120)
    website: HttpUrl | None = None
    department: str = Field(min_length=2, max_length=80)
    subject: str = Field(min_length=2, max_length=120)
    message: str = Field(min_length=3, max_length=5000)
    correlation_id: str | None = Field(default=None, max_length=120)
    honeypot_trap: str | None = Field(default=None, max_length=120)

    @field_validator("name", "department", "subject", "message", mode="before")
    @classmethod
    def normalize_required_text(cls, value: str | None) -> str:
        if value is None:
            return ""
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("Field cannot be empty.")
        return normalized

    @field_validator("company", "honeypot_trap", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class ContactMessageResponse(BaseModel):
    ok: bool
    correlation_id: str
    ticket_number: str
    confirmation_sent: bool


def _resolve_env_email(*keys: str, default: str, db: Session | None = None) -> str:
    if db is not None:
        try:
            from core.db_settings_resolver import resolve_db_setting

            for key in keys:
                val = resolve_db_setting(key, db)
                if val and str(val).strip():
                    return str(val).strip()
            return default
        except Exception:
            pass
    for key in keys:
        value = str(getattr(settings, key, "") or "").strip()
        if value:
            return value
    return default


def _resolve_support_inbox(db: Session | None = None) -> str:
    return _resolve_env_email(
        "CONTACT_INBOX_ADDRESS", "SUPPORT_EMAIL", default=DEFAULT_SUPPORT_INBOX, db=db
    )


def _resolve_billing_inbox(db: Session | None = None) -> str:
    return _resolve_env_email("BILLING_EMAIL", default=DEFAULT_BILLING_INBOX, db=db)


def _resolve_privacy_inbox(db: Session | None = None) -> str:
    return _resolve_env_email("PRIVACY_EMAIL", default=DEFAULT_PRIVACY_INBOX, db=db)


def _resolve_contact_inbox(department: str | None, db: Session | None = None) -> str:
    normalized = (department or "").strip().lower()
    if any(token in normalized for token in ("billing", "invoice", "payment", "subscription")):
        return _resolve_billing_inbox(db=db)
    if any(token in normalized for token in ("security", "privacy", "compliance", "legal", "data")):
        return _resolve_privacy_inbox(db=db)
    return _resolve_support_inbox(db=db)


def _resolve_ticket_prefix() -> str:
    configured = (
        str(
            getattr(settings, "CONTACT_TICKET_PREFIX", DEFAULT_TICKET_PREFIX)
            or DEFAULT_TICKET_PREFIX
        )
        .strip()
        .upper()
    )
    return configured or DEFAULT_TICKET_PREFIX


def _generate_ticket_number() -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_suffix = uuid.uuid4().hex[:6].upper()
    prefix = _resolve_ticket_prefix()
    return f"{prefix}-{today}-{random_suffix}"


def _build_support_plain_text(
    payload: ContactMessageRequest, correlation_id: str, ticket_number: str
) -> str:
    website = str(payload.website) if payload.website else "Not provided"
    company = payload.company or "Not provided"
    return "\n".join(
        [
            "New contact form submission",
            f"Ticket Number: {ticket_number}",
            f"Correlation ID: {correlation_id}",
            "",
            f"Department: {payload.department}",
            f"Subject: {payload.subject}",
            "",
            f"Name: {payload.name}",
            f"Email: {payload.email}",
            f"Company: {company}",
            f"Website: {website}",
            "",
            "Message:",
            payload.message,
        ]
    )


def _build_confirmation_plain_text(payload: ContactMessageRequest, ticket_number: str) -> str:
    return "\n".join(
        [
            f"Hi {payload.name},",
            "",
            "We received your support request.",
            f"Ticket Number: {ticket_number}",
            f"Department: {payload.department}",
            f"Subject: {payload.subject}",
            "",
            "Our team will review your message and get back to you as soon as possible.",
            "",
            "Please keep this ticket number in your replies.",
            "",
            "Thanks,",
            "Qiko Signal Support",
        ]
    )


@router.post("/contact", response_model=ContactMessageResponse)
async def submit_contact_form(
    payload: ContactMessageRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    correlation_id = (
        payload.correlation_id or request.headers.get("X-Request-ID") or str(uuid.uuid4())
    )
    ticket_number = _generate_ticket_number()

    # Anti-Spam Check: Honeypot field
    if payload.honeypot_trap:
        logger.warning(
            "Contact form spam attempt detected (honeypot field filled, correlation_id=%s). Discarding submission.",
            correlation_id,
        )
        return ContactMessageResponse(
            ok=True,
            correlation_id=correlation_id,
            ticket_number=ticket_number,
            confirmation_sent=True,
        )

    recipient = _resolve_contact_inbox(payload.department, db=db)
    email_subject = f"[Ticket {ticket_number}] [Contact][{payload.department}] {payload.subject} - {payload.name}"
    email_text = _build_support_plain_text(payload, correlation_id, ticket_number)

    try:
        await asyncio.to_thread(
            send_email,
            to=recipient,
            subject=email_subject,
            html=None,
            text=email_text,
            category="contact_form",
            correlation_id=correlation_id,
            db=db,
        )
    except socket.gaierror as exc:
        smtp_host = str(getattr(settings, "SMTP_HOST", "") or "").strip() or "unset"
        logger.exception(
            "Contact form delivery failed due to SMTP DNS resolution (correlation_id=%s, smtp_host=%s): %s",
            correlation_id,
            smtp_host,
            exc,
        )
        raise HTTPException(
            status_code=502,
            detail=translate_backend_message(
                "errors.smtp_host_dns_failed",
                f"SMTP host '{smtp_host}' could not be resolved. Update SMTP_HOST to a valid mail server host.",
                request=request,
            ),
        ) from exc
    except Exception as exc:
        logger.exception(
            "Contact form delivery failed (correlation_id=%s): %s",
            correlation_id,
            exc,
        )
        raise HTTPException(
            status_code=502,
            detail=translate_backend_message(
                "errors.contact_delivery_failed",
                "Unable to deliver your message right now. Please try again shortly.",
                request=request,
            ),
        ) from exc

    confirmation_sent = True
    confirmation_subject = f"[Ticket {ticket_number}] We received your request: {payload.subject}"
    confirmation_text = _build_confirmation_plain_text(payload, ticket_number)
    try:
        await asyncio.to_thread(
            send_email,
            to=str(payload.email),
            subject=confirmation_subject,
            html=None,
            text=confirmation_text,
            category="contact_form_confirmation",
            correlation_id=correlation_id,
            db=db,
        )
    except Exception as exc:
        confirmation_sent = False
        logger.exception(
            "Contact confirmation email failed (ticket_number=%s, correlation_id=%s): %s",
            ticket_number,
            correlation_id,
            exc,
        )

    return ContactMessageResponse(
        ok=True,
        correlation_id=correlation_id,
        ticket_number=ticket_number,
        confirmation_sent=confirmation_sent,
    )
