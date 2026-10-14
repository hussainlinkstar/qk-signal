from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import dns.exception
import dns.resolver
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
from core.config import settings
from services.cloudflare_custom_hostname_service import (
    ensure_cloudflare_custom_hostname,
    is_cloudflare_custom_hostname_configured,
    map_cloudflare_hostname_to_local_status,
)
from services.tenant_context import get_tenant_workspace_id

DEFAULT_PRIMARY_COLOR = "#6366F1"
DEFAULT_SECONDARY_COLOR = "#22D3EE"
DEFAULT_SSL_STATUS = "pending_verification"
ACTIVE_SSL_STATUS = "active"
PENDING_SSL_STATUS = "pending_ssl"
ERROR_SSL_STATUS = "error"
DOMAIN_PATTERN = re.compile(
    r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)


def normalize_hex_color(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if not re.fullmatch(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", normalized):
        raise ValueError(f"{field_name} must be a valid hex color (e.g. #0EA5E9).")
    return normalized


def normalize_custom_domain(value: str) -> str:
    normalized = str(value or "").strip().lower().rstrip(".")
    normalized = normalized.replace("https://", "").replace("http://", "")
    normalized = normalized.split("/", 1)[0].split(":", 1)[0]
    if not DOMAIN_PATTERN.fullmatch(normalized):
        raise ValueError("Enter a valid subdomain such as audit.agencyname.com.")
    return normalized


def normalize_optional_text(value: str | None, *, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized[:max_length] or None


def normalize_optional_url(value: str | None, *, max_length: int = 2000) -> str | None:
    normalized = normalize_optional_text(value, max_length=max_length)
    if normalized is None:
        return None
    if normalized.startswith("http://") or normalized.startswith("https://"):
        return normalized
    raise ValueError("URL values must start with http:// or https://.")


def normalize_optional_email(value: str | None) -> str | None:
    normalized = normalize_optional_text(value, max_length=255)
    if normalized is None:
        return None
    if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise ValueError("Enter a valid reply-to email address.")
    return normalized.lower()


def normalize_host(value: str | None) -> str:
    host = str(value or "").strip().lower()
    if not host:
        return ""
    if host.startswith("http://") or host.startswith("https://"):
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].split(":", 1)[0].rstrip(".")
    return host


def resolve_custom_domain_cname_target() -> str | None:
    """Resolve the platform CNAME target for workspace custom domains.

    Single source used by API instructions and new domain records. The value
    is operator-supplied via ``CUSTOM_DOMAIN_CNAME_TARGET`` and deliberately
    has no built-in default: when the deployment has not configured an
    approved hostname, or configured an invalid one, this returns None so
    callers surface an unavailable state instead of an invented target.
    """
    normalized = normalize_host(getattr(settings, "CUSTOM_DOMAIN_CNAME_TARGET", None))
    if not normalized or not DOMAIN_PATTERN.fullmatch(normalized):
        return None
    return normalized


def _system_hosts() -> set[str]:
    hosts = {
        "localhost",
        "127.0.0.1",
        "backend",
        "frontend",
    }
    for candidate in (
        settings.DOMAIN,
        settings.FRONTEND_URL,
        settings.APP_BASE_URL,
        settings.BACKEND_PUBLIC_URL,
        settings.CUSTOM_DOMAIN_CNAME_TARGET,
    ):
        normalized = normalize_host(candidate)
        if normalized:
            hosts.add(normalized)
            if normalized.startswith("www."):
                hosts.add(normalized[4:])
    extra_hosts = str(getattr(settings, "CUSTOM_DOMAIN_SYSTEM_HOSTS", "") or "").split(",")
    for raw_host in extra_hosts:
        normalized = normalize_host(raw_host)
        if normalized:
            hosts.add(normalized)
    return hosts


def platform_public_hosts() -> set[str]:
    hosts: set[str] = set()
    for candidate in (
        settings.DOMAIN,
        settings.FRONTEND_URL,
        settings.APP_BASE_URL,
        settings.BACKEND_PUBLIC_URL,
    ):
        normalized = normalize_host(candidate)
        if not normalized:
            continue
        hosts.add(normalized)
        if not normalized.startswith("www."):
            hosts.add(f"www.{normalized}")
    return hosts


def is_custom_tenant_host(host: str | None) -> bool:
    normalized = normalize_host(host)
    if not normalized:
        return False
    return normalized not in _system_hosts()


def _owner_branding_fallback(workspace: models.Workspace) -> dict[str, Any]:
    owner = workspace.owner
    return {
        "custom_logo_url": getattr(owner, "custom_logo_url", None) if owner else None,
        "company_name": getattr(owner, "company_name", None) if owner else None,
        "primary_color": normalize_hex_color(
            getattr(owner, "primary_color", None) if owner else None,
            field_name="primary_color",
        ),
        "secondary_color": normalize_hex_color(
            getattr(owner, "secondary_color", None) if owner else None,
            field_name="secondary_color",
        ),
    }


def resolve_workspace_branding(workspace: models.Workspace) -> dict[str, Any]:
    fallback = _owner_branding_fallback(workspace)
    company_name = (
        normalize_optional_text(workspace.company_name, max_length=255)
        or fallback["company_name"]
        or workspace.name
    )
    page_title = (
        normalize_optional_text(workspace.custom_page_title, max_length=255) or company_name
    )
    return {
        "workspace_id": workspace.id,
        "workspace_name": workspace.name,
        "company_name": company_name,
        "custom_logo_url": normalize_optional_text(workspace.custom_logo_url, max_length=2000)
        or fallback["custom_logo_url"],
        "primary_color": normalize_hex_color(workspace.primary_color, field_name="primary_color")
        or fallback["primary_color"]
        or DEFAULT_PRIMARY_COLOR,
        "secondary_color": normalize_hex_color(
            workspace.secondary_color, field_name="secondary_color"
        )
        or fallback["secondary_color"]
        or DEFAULT_SECONDARY_COLOR,
        "custom_favicon_url": normalize_optional_text(
            workspace.custom_favicon_url, max_length=2000
        ),
        "custom_page_title": page_title,
        "custom_meta_description": normalize_optional_text(
            workspace.custom_meta_description, max_length=300
        ),
        "hide_powered_by": bool(workspace.hide_powered_by),
        "email_sender_name": normalize_optional_text(workspace.email_sender_name, max_length=255),
        "email_reply_to": normalize_optional_email(workspace.email_reply_to),
        "social_facebook_url": normalize_optional_url(
            workspace.social_facebook_url, max_length=512
        ),
        "social_x_url": normalize_optional_url(workspace.social_x_url, max_length=512),
        "social_instagram_url": normalize_optional_url(
            workspace.social_instagram_url, max_length=512
        ),
        "social_linkedin_url": normalize_optional_url(
            workspace.social_linkedin_url, max_length=512
        ),
        "social_youtube_url": normalize_optional_url(workspace.social_youtube_url, max_length=512),
        "social_tiktok_url": normalize_optional_url(workspace.social_tiktok_url, max_length=512),
        "company_address": normalize_optional_text(workspace.company_address, max_length=1000),
        "company_legal_name": normalize_optional_text(workspace.company_legal_name, max_length=255),
        "company_trademark_text": normalize_optional_text(
            workspace.company_trademark_text, max_length=512
        ),
        "footer_about_url": normalize_optional_url(workspace.footer_about_url, max_length=512),
        "footer_blog_url": normalize_optional_url(workspace.footer_blog_url, max_length=512),
        "footer_support_url": normalize_optional_url(workspace.footer_support_url, max_length=512),
        "footer_legal_url": normalize_optional_url(workspace.footer_legal_url, max_length=512),
        "footer_preferences_url": normalize_optional_url(
            workspace.footer_preferences_url, max_length=512
        ),
        "footer_privacy_url": normalize_optional_url(workspace.footer_privacy_url, max_length=512),
    }


def apply_workspace_branding(
    *,
    workspace: models.Workspace,
    payload: dict[str, Any],
) -> models.Workspace:
    if "custom_logo_url" in payload:
        workspace.custom_logo_url = normalize_optional_text(
            payload.get("custom_logo_url"), max_length=2000
        )
    if "company_name" in payload:
        workspace.company_name = normalize_optional_text(
            payload.get("company_name"), max_length=255
        )
    if "primary_color" in payload:
        workspace.primary_color = normalize_hex_color(
            payload.get("primary_color"), field_name="primary_color"
        )
    if "secondary_color" in payload:
        workspace.secondary_color = normalize_hex_color(
            payload.get("secondary_color"), field_name="secondary_color"
        )
    if "custom_favicon_url" in payload:
        workspace.custom_favicon_url = normalize_optional_text(
            payload.get("custom_favicon_url"), max_length=2000
        )
    if "custom_page_title" in payload:
        workspace.custom_page_title = normalize_optional_text(
            payload.get("custom_page_title"), max_length=255
        )
    if "custom_meta_description" in payload:
        workspace.custom_meta_description = normalize_optional_text(
            payload.get("custom_meta_description"),
            max_length=300,
        )
    if "hide_powered_by" in payload:
        workspace.hide_powered_by = bool(payload.get("hide_powered_by"))
    if "email_sender_name" in payload:
        workspace.email_sender_name = normalize_optional_text(
            payload.get("email_sender_name"), max_length=255
        )
    if "email_reply_to" in payload:
        workspace.email_reply_to = normalize_optional_email(payload.get("email_reply_to"))
    if "social_facebook_url" in payload:
        workspace.social_facebook_url = normalize_optional_url(
            payload.get("social_facebook_url"), max_length=512
        )
    if "social_x_url" in payload:
        workspace.social_x_url = normalize_optional_url(payload.get("social_x_url"), max_length=512)
    if "social_instagram_url" in payload:
        workspace.social_instagram_url = normalize_optional_url(
            payload.get("social_instagram_url"), max_length=512
        )
    if "social_linkedin_url" in payload:
        workspace.social_linkedin_url = normalize_optional_url(
            payload.get("social_linkedin_url"), max_length=512
        )
    if "social_youtube_url" in payload:
        workspace.social_youtube_url = normalize_optional_url(
            payload.get("social_youtube_url"), max_length=512
        )
    if "social_tiktok_url" in payload:
        workspace.social_tiktok_url = normalize_optional_url(
            payload.get("social_tiktok_url"), max_length=512
        )
    if "company_address" in payload:
        workspace.company_address = normalize_optional_text(
            payload.get("company_address"), max_length=1000
        )
    if "company_legal_name" in payload:
        workspace.company_legal_name = normalize_optional_text(
            payload.get("company_legal_name"), max_length=255
        )
    if "company_trademark_text" in payload:
        workspace.company_trademark_text = normalize_optional_text(
            payload.get("company_trademark_text"),
            max_length=512,
        )
    if "footer_about_url" in payload:
        workspace.footer_about_url = normalize_optional_url(
            payload.get("footer_about_url"), max_length=512
        )
    if "footer_blog_url" in payload:
        workspace.footer_blog_url = normalize_optional_url(
            payload.get("footer_blog_url"), max_length=512
        )
    if "footer_support_url" in payload:
        workspace.footer_support_url = normalize_optional_url(
            payload.get("footer_support_url"), max_length=512
        )
    if "footer_legal_url" in payload:
        workspace.footer_legal_url = normalize_optional_url(
            payload.get("footer_legal_url"), max_length=512
        )
    if "footer_preferences_url" in payload:
        workspace.footer_preferences_url = normalize_optional_url(
            payload.get("footer_preferences_url"),
            max_length=512,
        )
    if "footer_privacy_url" in payload:
        workspace.footer_privacy_url = normalize_optional_url(
            payload.get("footer_privacy_url"), max_length=512
        )
    return workspace


def list_workspace_custom_domains(
    db: Session,
    *,
    workspace_id: int,
) -> list[models.CustomDomain]:
    return (
        db.query(models.CustomDomain)
        .filter(models.CustomDomain.workspace_id == workspace_id)
        .order_by(
            (models.CustomDomain.ssl_status == ACTIVE_SSL_STATUS).desc(),
            models.CustomDomain.created_at.asc(),
            models.CustomDomain.id.asc(),
        )
        .all()
    )


def create_workspace_custom_domain(
    db: Session,
    *,
    workspace_id: int,
    domain: str,
) -> models.CustomDomain:
    normalized_domain = normalize_custom_domain(domain)
    existing = (
        db.query(models.CustomDomain)
        .filter(models.CustomDomain.domain == normalized_domain)
        .first()
    )
    if existing and existing.workspace_id != workspace_id:
        raise HTTPException(
            status_code=409, detail="This domain is already linked to another workspace."
        )
    if existing:
        # Keep the stored dns_target: the customer already pointed DNS at it.
        existing.verified = False
        existing.ssl_status = DEFAULT_SSL_STATUS
        existing.verification_error = None
        existing.activated_at = None
        existing.verification_checked_at = None
        return existing

    dns_target = resolve_custom_domain_cname_target()
    if dns_target is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Custom domains are unavailable: the platform DNS target is not "
                "configured on this deployment."
            ),
        )

    custom_domain = models.CustomDomain(
        workspace_id=workspace_id,
        domain=normalized_domain,
        dns_target=dns_target,
        verified=False,
        ssl_status=DEFAULT_SSL_STATUS,
        schema_version="1",
    )
    db.add(custom_domain)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        # Re-check after the concurrent INSERT committed.
        existing = (
            db.query(models.CustomDomain)
            .filter(models.CustomDomain.domain == normalized_domain)
            .first()
        )
        if existing and existing.workspace_id != workspace_id:
            raise HTTPException(
                status_code=409, detail="This domain is already linked to another workspace."
            )
        if existing:
            existing.verified = False
            existing.ssl_status = DEFAULT_SSL_STATUS
            existing.verification_error = None
            existing.activated_at = None
            existing.verification_checked_at = None
            return existing
        raise HTTPException(
            status_code=409, detail="This domain is already linked to another workspace."
        )
    return custom_domain


def delete_workspace_custom_domain(
    db: Session,
    *,
    workspace_id: int,
    domain_id: int,
) -> bool:
    custom_domain = (
        db.query(models.CustomDomain)
        .filter(
            models.CustomDomain.id == domain_id,
            models.CustomDomain.workspace_id == workspace_id,
        )
        .first()
    )
    if custom_domain is None:
        return False
    db.delete(custom_domain)
    return True


def _resolve_cname_targets(domain: str) -> list[str]:
    try:
        answers = dns.resolver.resolve(domain, "CNAME")
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
        return []
    targets: list[str] = []
    for answer in answers:
        if hasattr(answer, "target"):
            targets.append(str(answer.target).rstrip(".").lower())
    return targets


def _resolve_ip_targets(domain: str, record_type: str) -> set[str]:
    try:
        answers = dns.resolver.resolve(domain, record_type)
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
        return set()
    values: set[str] = set()
    for answer in answers:
        values.add(str(answer).strip().lower())
    return values


def verify_workspace_custom_domain(
    db: Session,
    *,
    custom_domain: models.CustomDomain,
) -> models.CustomDomain:
    expected_target = normalize_host(custom_domain.dns_target)
    checked_at = datetime.now(timezone.utc)

    try:
        cname_targets = _resolve_cname_targets(custom_domain.domain)
        a_matches = False
        if expected_target and expected_target not in cname_targets:
            expected_a = _resolve_ip_targets(expected_target, "A")
            expected_aaaa = _resolve_ip_targets(expected_target, "AAAA")
            domain_a = _resolve_ip_targets(custom_domain.domain, "A")
            domain_aaaa = _resolve_ip_targets(custom_domain.domain, "AAAA")
            a_matches = bool((expected_a & domain_a) or (expected_aaaa & domain_aaaa))

        if expected_target in cname_targets or a_matches:
            custom_domain.verified = True
            custom_domain.verification_error = None
            custom_domain.verification_checked_at = checked_at
            if is_cloudflare_custom_hostname_configured(db):
                snapshot = ensure_cloudflare_custom_hostname(
                    hostname=custom_domain.domain,
                    workspace_id=custom_domain.workspace_id,
                    db=db,
                )
                custom_domain.ssl_status, custom_domain.verification_error = (
                    map_cloudflare_hostname_to_local_status(snapshot)
                )
                if custom_domain.ssl_status == ACTIVE_SSL_STATUS:
                    custom_domain.activated_at = checked_at
                else:
                    custom_domain.activated_at = None
            elif bool(settings.CUSTOM_DOMAIN_AUTO_ACTIVATE_ON_VERIFY):
                custom_domain.ssl_status = ACTIVE_SSL_STATUS
                custom_domain.activated_at = checked_at
            else:
                custom_domain.ssl_status = PENDING_SSL_STATUS
                custom_domain.activated_at = None
            return custom_domain

        custom_domain.verified = False
        custom_domain.ssl_status = ERROR_SSL_STATUS
        custom_domain.verification_checked_at = checked_at
        custom_domain.activated_at = None
        custom_domain.verification_error = (
            f"DNS mismatch. Point the domain to {custom_domain.dns_target} via CNAME."
        )
        return custom_domain
    except (
        dns.resolver.NXDOMAIN,
        dns.resolver.NoAnswer,
        dns.resolver.NoNameservers,
        dns.exception.Timeout,
    ) as exc:
        custom_domain.verified = False
        custom_domain.ssl_status = ERROR_SSL_STATUS
        custom_domain.verification_checked_at = checked_at
        custom_domain.activated_at = None
        custom_domain.verification_error = f"DNS lookup failed: {exc.__class__.__name__}."
        return custom_domain


def serialize_custom_domain(custom_domain: models.CustomDomain) -> dict[str, Any]:
    return {
        "id": custom_domain.id,
        "domain": custom_domain.domain,
        "dns_target": custom_domain.dns_target,
        "verified": bool(custom_domain.verified),
        "ssl_status": str(custom_domain.ssl_status or DEFAULT_SSL_STATUS),
        "verification_error": normalize_optional_text(
            custom_domain.verification_error, max_length=500
        ),
        "verification_checked_at": (
            custom_domain.verification_checked_at.isoformat()
            if custom_domain.verification_checked_at
            else None
        ),
        "activated_at": custom_domain.activated_at.isoformat()
        if custom_domain.activated_at
        else None,
        "created_at": custom_domain.created_at.isoformat() if custom_domain.created_at else None,
        "preview_url": f"https://{custom_domain.domain}",
    }


def resolve_workspace_for_tenant_context(
    db: Session,
    *,
    user: models.User,
) -> models.Workspace | None:
    tenant_workspace_id = get_tenant_workspace_id()
    if tenant_workspace_id is None:
        return None

    workspace = (
        db.query(models.Workspace).filter(models.Workspace.id == tenant_workspace_id).first()
    )
    if workspace is None:
        return None

    has_access = (
        workspace.owner_id == user.id
        or db.query(models.WorkspaceUser.id)
        .filter(
            models.WorkspaceUser.workspace_id == tenant_workspace_id,
            models.WorkspaceUser.user_id == user.id,
        )
        .first()
        is not None
    )
    if not has_access:
        raise HTTPException(
            status_code=403, detail="This custom domain is not linked to your workspace access."
        )
    return workspace


def resolve_workspace_by_host(
    db: Session,
    *,
    host: str | None,
) -> tuple[models.Workspace | None, models.CustomDomain | None]:
    normalized_host = normalize_host(host)
    if not is_custom_tenant_host(normalized_host):
        return None, None

    custom_domain = (
        db.query(models.CustomDomain)
        .filter(
            models.CustomDomain.domain == normalized_host,
            models.CustomDomain.verified.is_(True),
            models.CustomDomain.ssl_status == ACTIVE_SSL_STATUS,
        )
        .first()
    )
    if custom_domain is None:
        return None, None

    workspace = (
        db.query(models.Workspace).filter(models.Workspace.id == custom_domain.workspace_id).first()
    )
    return workspace, custom_domain


def is_custom_domain_tls_ready(
    db: Session,
    *,
    domain: str | None,
) -> bool:
    _workspace, custom_domain = resolve_workspace_by_host(db, host=domain)
    return custom_domain is not None


def is_tls_host_allowed(
    db: Session,
    *,
    domain: str | None,
) -> bool:
    normalized = normalize_host(domain)
    if not normalized:
        return False
    if normalized in platform_public_hosts():
        return True
    return is_custom_domain_tls_ready(db, domain=normalized)
