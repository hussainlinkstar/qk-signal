from __future__ import annotations

from fnmatch import fnmatch

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from core.config import settings
from database import SessionLocal, get_db
from services.custom_domain_service import (
    normalize_host,
    platform_public_hosts,
    resolve_workspace_by_host,
)
from services.tenant_context import (
    reset_active_workspace_id,
    reset_tenant_domain,
    reset_tenant_workspace_id,
    set_active_workspace_id,
    set_tenant_domain,
    set_tenant_workspace_id,
)


def _configured_system_host_patterns() -> list[str]:
    patterns: list[str] = []
    for raw_host in settings.allowed_hosts:
        candidate = str(raw_host or "").strip().lower().rstrip(".")
        if not candidate or candidate == "*":
            continue
        if "*" in candidate:
            patterns.append(candidate)
            continue

        normalized = normalize_host(candidate)
        if not normalized:
            continue
        patterns.append(normalized)
        if normalized.startswith("www."):
            patterns.append(normalized[4:])

    patterns.extend(sorted(platform_public_hosts()))

    if settings.ENVIRONMENT != "production":
        patterns.extend(["localhost", "127.0.0.1", "backend", "frontend", "testserver"])

    return list(dict.fromkeys(patterns))


def _extract_request_host(request: Request) -> str:
    raw_host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    forwarded_chain = raw_host.split(",", 1)[0].strip()
    return normalize_host(forwarded_chain)


def _is_allowed_system_host(host: str | None) -> bool:
    normalized = normalize_host(host)
    if not normalized:
        return False

    for pattern in _configured_system_host_patterns():
        if "*" in pattern:
            if fnmatch(normalized, pattern):
                return True
            continue
        if normalized == pattern:
            return True
    return False


async def tenant_resolver_middleware(request: Request, call_next):
    host = _extract_request_host(request)
    if not host:
        return JSONResponse(status_code=400, content={"detail": "Invalid host header."})

    workspace_id = None
    resolved_domain = None
    if not _is_allowed_system_host(host):
        db_override = getattr(request.app, "dependency_overrides", {}).get(get_db)
        db_gen = None

        if db_override:
            db_gen = db_override()
            db: Session = next(db_gen)
        else:
            db = SessionLocal()

        try:
            workspace, custom_domain = resolve_workspace_by_host(db, host=host)
            if workspace is None or custom_domain is None:
                return JSONResponse(status_code=400, content={"detail": "Invalid host header."})
            workspace_id = workspace.id
            resolved_domain = custom_domain.domain
        finally:
            if db_override and db_gen:
                try:
                    next(db_gen)
                except StopIteration:
                    pass
            else:
                db.close()

    # When not locked to a custom-domain tenant, allow the caller to select a
    # workspace explicitly via the X-Workspace-Id request header.
    active_workspace_id: int | None = None
    if workspace_id is None:
        raw_workspace_header = request.headers.get("x-workspace-id", "").strip()
        if raw_workspace_header.isdigit():
            active_workspace_id = int(raw_workspace_header)

    workspace_token = set_tenant_workspace_id(workspace_id)
    domain_token = set_tenant_domain(resolved_domain)
    active_token = set_active_workspace_id(active_workspace_id)
    request.state.tenant_workspace_id = workspace_id
    request.state.tenant_domain = resolved_domain

    try:
        return await call_next(request)
    finally:
        reset_active_workspace_id(active_token)
        reset_tenant_domain(domain_token)
        reset_tenant_workspace_id(workspace_token)
