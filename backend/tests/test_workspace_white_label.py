from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import main
import models
from database import Base
from routers.portal_router import get_portal_branding
from routers.workspace_router import (
    WorkspaceEmailFooterUpdateRequest,
    WorkspaceCustomDomainCreateRequest,
    WorkspaceWhiteLabelBrandingRequest,
    confirm_tenant_domain_activation,
    create_current_workspace_custom_domain,
    get_current_tenant_branding,
    get_current_workspace_email_footer_settings,
    get_current_workspace_white_label_settings,
    update_current_workspace_email_footer_settings,
    update_current_workspace_white_label_settings,
    verify_current_workspace_custom_domain,
)
from services.workspace_rbac import attach_portal_access_context


def _build_db() -> tuple[Session, Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory(), engine


def _cleanup(db: Session, engine: Engine) -> None:
    main.app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


def _seed_workspace(db: Session) -> tuple[models.User, models.Workspace, models.User]:
    owner = models.User(
        email="owner@example.com",
        hashed_password="x",
        role="user",
        credits=50,
        company_name="Owner Brand",
        custom_logo_url="https://cdn.example.com/user-logo.svg",
        primary_color="#111111",
        secondary_color="#222222",
    )
    db.add(owner)
    db.flush()

    workspace = models.Workspace(
        name="Agency Workspace",
        owner_id=owner.id,
        company_name="Workspace Brand",
        custom_logo_url="https://cdn.example.com/workspace-logo.svg",
        primary_color="#FF4D2D",
        secondary_color="#14B8A6",
        custom_page_title="Workspace Brand Portal",
        custom_favicon_url="https://cdn.example.com/favicon.png",
        hide_powered_by=True,
        email_sender_name="Workspace Ops",
        email_reply_to="ops@agency.example",
    )
    db.add(workspace)
    db.flush()

    db.add(
        models.WorkspaceUser(
            workspace_id=workspace.id,
            user_id=owner.id,
            role=models.WorkspaceRole.ADMIN,
        )
    )
    db.add(
        models.Subscription(
            user_id=owner.id,
            stripe_customer_id="cus_white_label",
            plan_type="plan_executive",
            status="active",
        )
    )
    portal_user = models.User(
        email="client@example.com",
        hashed_password="x",
        role="user",
        credits=0,
        company_name="Client User",
    )
    db.add(portal_user)
    db.flush()
    db.add(
        models.WorkspaceUser(
            workspace_id=workspace.id,
            user_id=portal_user.id,
            role=models.WorkspaceRole.CLIENT_READONLY,
        )
    )
    db.commit()
    db.refresh(owner)
    db.refresh(workspace)
    db.refresh(portal_user)
    return owner, workspace, portal_user


def test_workspace_white_label_settings_and_portal_branding_use_workspace_values() -> None:
    db, engine = _build_db()
    try:
        owner, workspace, portal_user = _seed_workspace(db)

        settings_payload = get_current_workspace_white_label_settings(user=owner, db=db)
        assert settings_payload["company_name"] == "Workspace Brand"
        assert settings_payload["custom_logo_url"] == "https://cdn.example.com/workspace-logo.svg"
        assert settings_payload["primary_color"] == "#FF4D2D"
        assert settings_payload["domains"] == []

        portal_access_user = attach_portal_access_context(db, user=portal_user)
        branding = get_portal_branding(user=portal_access_user, db=db, workspace_id=workspace.id)
        assert branding.agency_name == "Workspace Brand"
        assert branding.custom_logo_url == "https://cdn.example.com/workspace-logo.svg"
        assert branding.primary_color == "#FF4D2D"
        assert branding.hide_powered_by is True
    finally:
        _cleanup(db, engine)


def test_platform_domain_is_allowed_for_tls_activation(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    try:
        monkeypatch.setattr("services.custom_domain_service.settings.DOMAIN", "thothgraph.com")
        monkeypatch.setattr(
            "services.custom_domain_service.settings.FRONTEND_URL", "https://thothgraph.com"
        )
        monkeypatch.setattr(
            "services.custom_domain_service.settings.APP_BASE_URL", "https://thothgraph.com"
        )
        monkeypatch.setattr(
            "services.custom_domain_service.settings.BACKEND_PUBLIC_URL", "https://thothgraph.com"
        )

        activation_response = confirm_tenant_domain_activation(
            domain="thothgraph.com",
            db=db,
        )
        assert activation_response.status_code == 200
    finally:
        _cleanup(db, engine)


def test_workspace_custom_domain_verification_updates_status_and_tenant_branding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    try:
        owner, workspace, _portal_user = _seed_workspace(db)
        queued_templates: list[str] = []

        def _fake_queue_template_email(self, **kwargs):
            queued_templates.append(str(kwargs["template_key"]))
            return SimpleNamespace(id=1)

        def _fake_verify(_db, *, custom_domain):
            custom_domain.verified = True
            custom_domain.ssl_status = "active"
            custom_domain.verification_error = None
            custom_domain.activated_at = workspace.created_at
            custom_domain.verification_checked_at = workspace.created_at
            return custom_domain

        monkeypatch.setattr(
            "routers.workspace_router.verify_workspace_custom_domain",
            _fake_verify,
        )
        monkeypatch.setattr(
            "services.email_service.EmailService.queue_template_email",
            _fake_queue_template_email,
        )

        update_current_workspace_white_label_settings(
            payload=WorkspaceWhiteLabelBrandingRequest(
                company_name="Updated Workspace Brand",
                custom_page_title="Updated Workspace Login",
            ),
            user=owner,
            db=db,
        )

        created = create_current_workspace_custom_domain(
            payload=WorkspaceCustomDomainCreateRequest(domain="audit.agency.example"),
            user=owner,
            db=db,
        )
        assert created["domains"][0]["ssl_status"] == "pending_verification"

        verified = verify_current_workspace_custom_domain(
            domain_id=created["domains"][0]["id"],
            user=owner,
            db=db,
        )
        assert verified["domains"][0]["verified"] is True
        assert verified["domains"][0]["ssl_status"] == "active"
        assert queued_templates == [
            "workspace.domain_verified",
            "workspace.ssl_provisioned",
        ]

        tenant_request = SimpleNamespace(
            state=SimpleNamespace(
                tenant_workspace_id=workspace.id,
                tenant_domain="audit.agency.example",
            )
        )
        tenant_branding = get_current_tenant_branding(request=tenant_request, db=db)
        assert tenant_branding.company_name == "Updated Workspace Brand"
        assert tenant_branding.custom_page_title == "Updated Workspace Login"
        assert tenant_branding.active_domain == "audit.agency.example"

        activation_response = confirm_tenant_domain_activation(
            domain="audit.agency.example",
            db=db,
        )
        assert activation_response.status_code == 200
    finally:
        _cleanup(db, engine)


def test_workspace_email_footer_settings_roundtrip() -> None:
    db, engine = _build_db()
    try:
        owner, _workspace, _portal_user = _seed_workspace(db)

        initial = get_current_workspace_email_footer_settings(user=owner, db=db)
        assert initial["workspace_id"] > 0
        assert initial["social_linkedin_url"] is None
        assert initial["footer_privacy_url"] is None

        updated = update_current_workspace_email_footer_settings(
            payload=WorkspaceEmailFooterUpdateRequest(
                social_linkedin_url="https://linkedin.com/company/workspace-brand",
                social_x_url="https://x.com/workspacebrand",
                company_address="42 Orbit Avenue\nBucharest, Romania",
                company_legal_name="Workspace Brand SRL",
                company_trademark_text="Workspace Brand is a trademark of Workspace Brand SRL.",
                footer_about_url="https://workspace.example/about",
                footer_blog_url="https://workspace.example/blog",
                footer_support_url="https://workspace.example/support",
                footer_legal_url="https://workspace.example/legal",
                footer_preferences_url="https://workspace.example/preferences",
                footer_privacy_url="https://workspace.example/privacy",
            ),
            user=owner,
            db=db,
        )
        assert updated["social_linkedin_url"] == "https://linkedin.com/company/workspace-brand"
        assert updated["social_x_url"] == "https://x.com/workspacebrand"
        assert updated["company_legal_name"] == "Workspace Brand SRL"
        assert updated["footer_privacy_url"] == "https://workspace.example/privacy"

        white_label_payload = get_current_workspace_white_label_settings(user=owner, db=db)
        assert (
            white_label_payload["social_linkedin_url"]
            == "https://linkedin.com/company/workspace-brand"
        )
        assert white_label_payload["footer_support_url"] == "https://workspace.example/support"
        assert white_label_payload["company_trademark_text"] == (
            "Workspace Brand is a trademark of Workspace Brand SRL."
        )
    finally:
        _cleanup(db, engine)


def test_dns_verification_falls_back_to_a_records_on_no_cname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BUG-4 regression: NoAnswer on CNAME lookup must NOT short-circuit the A/AAAA fallback."""
    db, engine = _build_db()
    try:
        owner, workspace, _portal_user = _seed_workspace(db)

        from services.custom_domain_service import (
            create_workspace_custom_domain,
            verify_workspace_custom_domain,
        )

        custom_domain = create_workspace_custom_domain(
            db, workspace_id=workspace.id, domain="flat.agency.example"
        )
        db.flush()

        monkeypatch.setattr(
            "services.custom_domain_service.settings.CUSTOM_DOMAIN_CNAME_TARGET",
            "custom.thothgraph.com",
        )
        monkeypatch.setattr(
            "services.custom_domain_service.settings.CUSTOM_DOMAIN_AUTO_ACTIVATE_ON_VERIFY",
            True,
        )
        # Make cloudflare not configured so auto-activate path is used.
        monkeypatch.setattr(
            "services.custom_domain_service.is_cloudflare_custom_hostname_configured",
            lambda db=None: False,
        )

        import dns.resolver

        def _fake_resolve(domain, rtype):
            """CNAME raises NoAnswer; A returns matching IPs for both target and domain."""
            if rtype == "CNAME":
                raise dns.resolver.NoAnswer()
            if rtype == "A":
                result = SimpleNamespace()
                result.__iter__ = lambda self: iter(
                    [SimpleNamespace(__str__=lambda self: "1.2.3.4")]
                )

                # Return an object that yields "1.2.3.4"
                class FakeAnswer:
                    def __iter__(self_inner):
                        return iter(["1.2.3.4"])

                return FakeAnswer()
            return type("Empty", (), {"__iter__": lambda s: iter([])})()

        monkeypatch.setattr("services.custom_domain_service.dns.resolver.resolve", _fake_resolve)

        result = verify_workspace_custom_domain(db, custom_domain=custom_domain)
        assert result.verified is True
        assert result.ssl_status == "active"
    finally:
        _cleanup(db, engine)


def test_create_domain_race_returns_409_for_other_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BUG-5 regression: IntegrityError on concurrent INSERT raises clean 409."""
    db, engine = _build_db()
    try:
        owner, workspace, _portal_user = _seed_workspace(db)

        # Create second workspace
        owner2 = models.User(
            email="other@example.com", hashed_password="x", role="user", credits=10
        )
        db.add(owner2)
        db.flush()
        workspace2 = models.Workspace(name="Other WS", owner_id=owner2.id)
        db.add(workspace2)
        db.flush()
        db.commit()

        from services.custom_domain_service import create_workspace_custom_domain

        # First workspace claims the domain
        create_workspace_custom_domain(db, workspace_id=workspace.id, domain="race.example.com")
        db.commit()

        # Second workspace should get 409
        from fastapi import HTTPException as _HTTPException

        with pytest.raises(_HTTPException) as exc_info:
            create_workspace_custom_domain(
                db, workspace_id=workspace2.id, domain="race.example.com"
            )
        assert exc_info.value.status_code == 409
    finally:
        _cleanup(db, engine)
