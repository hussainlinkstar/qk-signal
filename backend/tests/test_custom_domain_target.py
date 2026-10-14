"""SIGV2-1022: single-configured custom-domain CNAME target.

Covers the shared resolver (AC1), the unavailable state on missing or
invalid configuration (AC1/AC2), agreement across settings, create and
verify surfaces (AC3), and stored-target compatibility for domains
created before the target changed (AC4).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from routers.workspace_router import (
    verify_current_workspace_custom_domain,
)
from services.custom_domain_service import (
    create_workspace_custom_domain,
    resolve_custom_domain_cname_target,
    verify_workspace_custom_domain,
)


def _build_db() -> tuple[Session, Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory(), engine


def _make_owner_workspace(
    db: Session, *, plan: str | None = "plan_executive"
) -> tuple[models.User, models.Workspace]:
    owner = models.User(email="owner@example.com", hashed_password="x", role="user", credits=50)
    db.add(owner)
    db.flush()
    workspace = models.Workspace(name="Agency Workspace", owner_id=owner.id)
    db.add(workspace)
    db.flush()
    db.add(
        models.WorkspaceUser(
            workspace_id=workspace.id,
            user_id=owner.id,
            role=models.WorkspaceRole.ADMIN,
        )
    )
    if plan is not None:
        db.add(
            models.Subscription(
                user_id=owner.id,
                stripe_customer_id=f"cus_{owner.id}",
                plan_type=plan,
                status="active",
            )
        )
    db.commit()
    return owner, workspace


def _set_target(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    monkeypatch.setattr(
        "services.custom_domain_service.settings.CUSTOM_DOMAIN_CNAME_TARGET",
        value,
    )


# ---------------------------------------------------------------------------
# Resolver behaviour (AC1)
# ---------------------------------------------------------------------------


def test_resolver_returns_configured_target_normalized(monkeypatch) -> None:
    _set_target(monkeypatch, "Verify.Qiko-Agency.example.")
    assert resolve_custom_domain_cname_target() == "verify.qiko-agency.example"


@pytest.mark.parametrize("bad", ["", "   ", "localhost", "not a host", "a" * 300])
def test_resolver_returns_none_on_missing_or_invalid(monkeypatch, bad: str) -> None:
    _set_target(monkeypatch, bad)
    assert resolve_custom_domain_cname_target() is None


def test_create_domain_unavailable_when_target_unconfigured(monkeypatch) -> None:
    db, engine = _build_db()
    try:
        _owner, workspace = _make_owner_workspace(db, plan=None)
        _set_target(monkeypatch, "")
        with pytest.raises(HTTPException) as exc_info:
            create_workspace_custom_domain(
                db, workspace_id=workspace.id, domain="audit.agency.example"
            )
        assert exc_info.value.status_code == 503
        assert "not configured" in exc_info.value.detail
        assert (
            db.query(models.CustomDomain)
            .filter(models.CustomDomain.domain == "audit.agency.example")
            .count()
            == 0
        )
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Settings, create and verify agree (AC3)
# ---------------------------------------------------------------------------


def test_settings_create_and_verify_surfaces_share_one_target(monkeypatch) -> None:
    db, engine = _build_db()
    try:
        owner, workspace = _make_owner_workspace(db, plan=None)
        _set_target(monkeypatch, "verify.agency-platform.example")

        created = create_workspace_custom_domain(
            db, workspace_id=workspace.id, domain="audit.agency.example"
        )
        db.commit()
        assert created.dns_target == "verify.agency-platform.example"

        from routers.workspace_router import _serialize_white_label_settings

        settings_payload = _serialize_white_label_settings(db=db, workspace=workspace)
        assert settings_payload["dns_target"] == "verify.agency-platform.example"
        assert settings_payload["domains"][0]["dns_target"] == created.dns_target

        monkeypatch.setattr(
            "services.custom_domain_service._resolve_cname_targets", lambda domain: set()
        )
        verified = verify_workspace_custom_domain(db, custom_domain=created)
        assert verified.verified is False
        assert "verify.agency-platform.example" in (verified.verification_error or "")
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_settings_target_is_null_when_unconfigured(monkeypatch) -> None:
    db, engine = _build_db()
    try:
        _owner, workspace = _make_owner_workspace(db, plan=None)
        _set_target(monkeypatch, "")
        from routers.workspace_router import _serialize_white_label_settings

        payload = _serialize_white_label_settings(db=db, workspace=workspace)
        assert payload["dns_target"] is None
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Persisted-target compatibility (AC4)
# ---------------------------------------------------------------------------


def test_recreate_preserves_stored_target(monkeypatch) -> None:
    db, engine = _build_db()
    try:
        _owner, workspace = _make_owner_workspace(db, plan=None)
        legacy = models.CustomDomain(
            workspace_id=workspace.id,
            domain="audit.agency.example",
            dns_target="legacy.thothgraph.example",
            verified=True,
            ssl_status="active",
            schema_version="1",
        )
        db.add(legacy)
        db.commit()

        _set_target(monkeypatch, "new.platform-target.example")
        result = create_workspace_custom_domain(
            db, workspace_id=workspace.id, domain="audit.agency.example"
        )
        assert result.dns_target == "legacy.thothgraph.example"
        # Re-adding still forces re-verification against the stored target.
        assert result.verified is False
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_legacy_domain_verifies_against_stored_target(monkeypatch) -> None:
    db, engine = _build_db()
    try:
        _owner, workspace = _make_owner_workspace(db, plan=None)
        legacy = models.CustomDomain(
            workspace_id=workspace.id,
            domain="audit.agency.example",
            dns_target="legacy.thothgraph.example",
            verified=False,
            ssl_status="pending_verification",
            schema_version="1",
        )
        db.add(legacy)
        db.commit()

        # The deployment now points at a different target; the legacy record
        # must still verify against the target the customer CNAME'd to.
        _set_target(monkeypatch, "new.platform-target.example")
        monkeypatch.setattr(
            "services.custom_domain_service._resolve_cname_targets",
            lambda domain: {"legacy.thothgraph.example"},
        )
        monkeypatch.setattr(
            "services.custom_domain_service.is_cloudflare_custom_hostname_configured",
            lambda db=None: False,
        )
        monkeypatch.setattr(
            "services.custom_domain_service.settings.CUSTOM_DOMAIN_AUTO_ACTIVATE_ON_VERIFY",
            True,
        )
        result = verify_workspace_custom_domain(db, custom_domain=legacy)
        assert result.verified is True
        assert result.ssl_status == "active"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_new_domain_records_configured_target(monkeypatch) -> None:
    db, engine = _build_db()
    try:
        _owner, workspace = _make_owner_workspace(db, plan=None)
        _set_target(monkeypatch, "new.platform-target.example")
        created = create_workspace_custom_domain(
            db, workspace_id=workspace.id, domain="audit.agency.example"
        )
        assert created.dns_target == "new.platform-target.example"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Ownership isolation
# ---------------------------------------------------------------------------


def test_foreign_workspace_domain_id_refused(monkeypatch) -> None:
    db, engine = _build_db()
    try:
        owner, workspace = _make_owner_workspace(db, plan="plan_executive")
        created = models.CustomDomain(
            workspace_id=workspace.id,
            domain="audit.agency.example",
            dns_target="verify.agency-platform.example",
            verified=False,
            ssl_status="pending_verification",
            schema_version="1",
        )
        db.add(created)

        foreign = models.User(
            email="foreign@example.com", hashed_password="x", role="user", credits=50
        )
        db.add(foreign)
        db.flush()
        foreign_workspace = models.Workspace(name="Foreign", owner_id=foreign.id)
        db.add(foreign_workspace)
        db.flush()
        db.add(
            models.WorkspaceUser(
                workspace_id=foreign_workspace.id,
                user_id=foreign.id,
                role=models.WorkspaceRole.ADMIN,
            )
        )
        db.add(
            models.Subscription(
                user_id=foreign.id,
                stripe_customer_id=f"cus_{foreign.id}",
                plan_type="plan_executive",
                status="active",
            )
        )
        db.commit()

        monkeypatch.setattr("routers.workspace_router.EmailService", lambda db: SimpleNamespace())
        with pytest.raises(HTTPException) as exc_info:
            verify_current_workspace_custom_domain(domain_id=created.id, user=foreign, db=db)
        assert exc_info.value.status_code == 404
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
