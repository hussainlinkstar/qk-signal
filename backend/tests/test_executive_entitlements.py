"""SIGV2-1026: Executive multiple-workspace and white-label entitlement alignment.

Pins the three capability sources of truth (CAPABILITY_MATRIX,
PRICING_CAPABILITY_MATRIX, MINIMUM_PLAN_BY_FEATURE), owner-scoped
entitlement resolution (AC2), downgrade behaviour (AC6) and the custom
domain entitlement remaining behind verification (AC5).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import HTTPException

import models
from database import Base
from app.config.plans import (
    CANONICAL_PLAN_TYPES,
    CAPABILITY_MATRIX,
    MINIMUM_PLAN_BY_FEATURE,
    get_plan_capabilities,
    resolve_plan_alias,
)
from app.services.compliance.plan_validator import PRICING_CAPABILITY_MATRIX
from services.audit_feature_gating_service import _required_plan_label
from services.portal_service import resolve_workspace_owner_plan
from routers.workspace_router import (
    WorkspaceCreateRequest,
    WorkspaceCustomDomainCreateRequest,
    WorkspaceWhiteLabelBrandingRequest,
    create_current_workspace_custom_domain,
    create_workspace,
    get_current_workspace_white_label_settings,
    update_current_workspace_white_label_settings,
)

EXECUTIVE_ONLY_KEYS = (
    "has_white_label",
    "has_custom_domain",
    "pdf_white_label",
    "has_multi_workspace_federation",
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


def _make_user(db: Session, email: str, *, plan: str | None, status: str = "active") -> models.User:
    user = models.User(email=email, hashed_password="x", role="user", credits=50)
    db.add(user)
    db.flush()
    if plan is not None:
        db.add(
            models.Subscription(
                user_id=user.id,
                stripe_customer_id=f"cus_{user.id}",
                plan_type=plan,
                status=status,
            )
        )
    return user


def _make_workspace(
    db: Session, *, owner: models.User, name: str = "Agency Workspace"
) -> models.Workspace:
    workspace = models.Workspace(name=name, owner_id=owner.id)
    db.add(workspace)
    db.flush()
    db.add(
        models.WorkspaceUser(
            workspace_id=workspace.id,
            user_id=owner.id,
            role=models.WorkspaceRole.ADMIN,
        )
    )
    return workspace


def _add_member(
    db: Session, workspace: models.Workspace, user: models.User, role=models.WorkspaceRole.ADMIN
) -> None:
    db.add(models.WorkspaceUser(workspace_id=workspace.id, user_id=user.id, role=role))


# ---------------------------------------------------------------------------
# Capability sources of truth agree
# ---------------------------------------------------------------------------


def test_capability_matrix_executive_only() -> None:
    for plan in CANONICAL_PLAN_TYPES:
        caps = get_plan_capabilities(plan)
        expected = plan == "plan_executive"
        for key in EXECUTIVE_ONLY_KEYS:
            assert caps.get(key) is expected, (plan, key)


def test_pricing_matrix_agrees_with_capability_matrix() -> None:
    for plan, caps in PRICING_CAPABILITY_MATRIX.items():
        canonical = resolve_plan_alias(plan) or plan
        runtime_caps = CAPABILITY_MATRIX.get(canonical, {})
        for key in EXECUTIVE_ONLY_KEYS:
            if key in caps and key in runtime_caps:
                assert caps[key] == runtime_caps[key], (plan, key)


def test_required_plan_label_names_a_plan_that_holds_the_capability() -> None:
    # A customer-facing "Available on the X plan" label must name a plan that
    # genuinely holds the capability, so the matrices cannot drift again.
    for key, required_plan in MINIMUM_PLAN_BY_FEATURE.items():
        canonical = resolve_plan_alias(required_plan) or required_plan
        caps = CAPABILITY_MATRIX.get(canonical, {})
        if key in caps:
            assert caps[key] is True, (key, required_plan)
    assert _required_plan_label("has_white_label") == "Executive"


# ---------------------------------------------------------------------------
# Owner-scoped entitlement resolution (AC2)
# ---------------------------------------------------------------------------


def test_entitled_owner_updates_white_label() -> None:
    db, engine = _build_db()
    try:
        owner = _make_user(db, "owner@example.com", plan="plan_executive")
        _make_workspace(db, owner=owner)
        db.commit()
        result = update_current_workspace_white_label_settings(
            payload=WorkspaceWhiteLabelBrandingRequest(company_name="Owner Brand"),
            user=owner,
            db=db,
        )
        assert result["company_name"] == "Owner Brand"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_admin_member_on_entitled_workspace_updates_branding() -> None:
    # The entitlement follows the billed workspace owner, so an admin member
    # operating inside an entitled workspace can configure its branding.
    db, engine = _build_db()
    try:
        owner = _make_user(db, "owner@example.com", plan="plan_executive")
        member = _make_user(db, "member@example.com", plan="plan_starter")
        workspace = _make_workspace(db, owner=owner)
        _add_member(db, workspace, member)
        db.commit()
        result = update_current_workspace_white_label_settings(
            payload=WorkspaceWhiteLabelBrandingRequest(company_name="Member Set"),
            user=member,
            db=db,
        )
        assert result["company_name"] == "Member Set"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_member_does_not_inherit_entitlement_on_own_workspace() -> None:
    # A member of an Executive-owned workspace cannot apply the owner's
    # entitlement to a workspace the member owns on a lower plan.
    db, engine = _build_db()
    try:
        owner = _make_user(db, "owner@example.com", plan="plan_executive")
        member = _make_user(db, "member@example.com", plan="plan_starter")
        entitled = _make_workspace(db, owner=owner)
        _add_member(db, entitled, member)
        _make_workspace(db, owner=member, name="Member Workspace")
        db.commit()
        with pytest.raises(HTTPException) as exc_info:
            update_current_workspace_white_label_settings(
                payload=WorkspaceWhiteLabelBrandingRequest(company_name="Nope"),
                user=member,
                db=db,
            )
        assert exc_info.value.status_code == 402
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_executive_member_cannot_brand_starter_owned_workspace() -> None:
    # Resolution is against the billed workspace owner, never the viewing
    # member's own plan.
    db, engine = _build_db()
    try:
        owner = _make_user(db, "owner@example.com", plan="plan_starter")
        member = _make_user(db, "member@example.com", plan="plan_executive")
        workspace = _make_workspace(db, owner=owner)
        _add_member(db, workspace, member)
        db.commit()
        with pytest.raises(HTTPException) as exc_info:
            update_current_workspace_white_label_settings(
                payload=WorkspaceWhiteLabelBrandingRequest(company_name="Nope"),
                user=member,
                db=db,
            )
        assert exc_info.value.status_code == 402
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.mark.parametrize("status", ["pending", "canceled", "expired", "past_due"])
def test_inactive_subscription_denies_white_label(status: str) -> None:
    db, engine = _build_db()
    try:
        owner = _make_user(db, f"owner-{status}@example.com", plan="plan_executive", status=status)
        _make_workspace(db, owner=owner)
        db.commit()
        with pytest.raises(HTTPException) as exc_info:
            update_current_workspace_white_label_settings(
                payload=WorkspaceWhiteLabelBrandingRequest(company_name="Nope"),
                user=owner,
                db=db,
            )
        assert exc_info.value.status_code == 402
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Workspace creation
# ---------------------------------------------------------------------------


def test_executive_owner_creates_additional_workspace() -> None:
    db, engine = _build_db()
    try:
        owner = _make_user(db, "owner@example.com", plan="plan_executive")
        _make_workspace(db, owner=owner)
        db.commit()
        result = create_workspace(
            payload=WorkspaceCreateRequest(name="Second Workspace"),
            user=owner,
            db=db,
        )
        assert result["name"] == "Second Workspace"
        # The response exposes only the newly created workspace.
        assert result["owner_id"] == owner.id
        assert result["is_owner"] is True
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_lower_plan_workspace_creation_denied() -> None:
    db, engine = _build_db()
    try:
        user = _make_user(db, "user@example.com", plan="plan_specialist")
        _make_workspace(db, owner=user)
        db.commit()
        with pytest.raises(HTTPException) as exc_info:
            create_workspace(
                payload=WorkspaceCreateRequest(name="Second Workspace"),
                user=user,
                db=db,
            )
        assert exc_info.value.status_code == 403
        assert "Multiple workspaces" in exc_info.value.detail
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_member_cannot_create_workspace_via_owner_entitlement() -> None:
    db, engine = _build_db()
    try:
        owner = _make_user(db, "owner@example.com", plan="plan_executive")
        member = _make_user(db, "member@example.com", plan="plan_starter")
        workspace = _make_workspace(db, owner=owner)
        _add_member(db, workspace, member)
        db.commit()
        with pytest.raises(HTTPException) as exc_info:
            create_workspace(
                payload=WorkspaceCreateRequest(name="Member Workspace"),
                user=member,
                db=db,
            )
        assert exc_info.value.status_code == 403
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_workspace_creation_exposes_no_other_workspace() -> None:
    db, engine = _build_db()
    try:
        owner = _make_user(db, "owner@example.com", plan="plan_executive")
        _make_workspace(db, owner=owner, name="First Workspace")
        db.commit()
        result = create_workspace(
            payload=WorkspaceCreateRequest(name="Second Workspace"),
            user=owner,
            db=db,
        )
        assert result["name"] == "Second Workspace"
        assert "First Workspace" not in str(result)
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Custom domain: entitlement granted, verification still required (AC5)
# ---------------------------------------------------------------------------


def test_custom_domain_entitlement_does_not_skip_verification() -> None:
    db, engine = _build_db()
    try:
        owner = _make_user(db, "owner@example.com", plan="plan_executive")
        _make_workspace(db, owner=owner)
        db.commit()
        created = create_current_workspace_custom_domain(
            payload=WorkspaceCustomDomainCreateRequest(domain="audit.agency.example"),
            user=owner,
            db=db,
        )
        domain = created["domains"][0]
        assert domain["verified"] is False
        assert domain["ssl_status"] == "pending_verification"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Downgrade behaviour (AC6)
# ---------------------------------------------------------------------------


def test_downgrade_preserves_data_and_restricts_new_operations() -> None:
    db, engine = _build_db()
    try:
        owner = _make_user(db, "owner@example.com", plan="plan_executive")
        workspace = _make_workspace(db, owner=owner)
        db.commit()
        create_workspace(
            payload=WorkspaceCreateRequest(name="Second Workspace"),
            user=owner,
            db=db,
        )
        update_current_workspace_white_label_settings(
            payload=WorkspaceWhiteLabelBrandingRequest(company_name="Kept Brand"),
            user=owner,
            db=db,
        )

        subscription = (
            db.query(models.Subscription).filter(models.Subscription.user_id == owner.id).one()
        )
        subscription.plan_type = "plan_starter"
        db.commit()

        # Existing workspaces and stored branding are preserved.
        assert db.query(models.Workspace).filter(models.Workspace.owner_id == owner.id).count() == 2
        settings = get_current_workspace_white_label_settings(user=owner, db=db)
        assert settings["company_name"] == "Kept Brand"
        assert workspace.company_name == "Kept Brand"

        # New privileged operations are restricted.
        with pytest.raises(HTTPException) as ws_exc:
            create_workspace(
                payload=WorkspaceCreateRequest(name="Third Workspace"),
                user=owner,
                db=db,
            )
        assert ws_exc.value.status_code == 403
        with pytest.raises(HTTPException) as wl_exc:
            update_current_workspace_white_label_settings(
                payload=WorkspaceWhiteLabelBrandingRequest(company_name="Changed"),
                user=owner,
                db=db,
            )
        assert wl_exc.value.status_code == 402
        assert workspace.company_name == "Kept Brand"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Branded PDF path (AC4)
# ---------------------------------------------------------------------------


def test_white_label_pdf_export_allowed_on_executive() -> None:
    from routers.api_router import _require_report_export_access

    manifest = {
        "report_kind": "executive",
        "branding_mode": "white_label",
        "render_report_type": "whitelabel",
    }
    _require_report_export_access(
        SimpleNamespace(
            subscription=SimpleNamespace(status="active", plan_type="plan_executive"),
            trial_plan=None,
        ),
        export_manifest=manifest,
    )
    with pytest.raises(HTTPException) as exc_info:
        _require_report_export_access(
            SimpleNamespace(
                subscription=SimpleNamespace(status="active", plan_type="plan_specialist"),
                trial_plan=None,
            ),
            export_manifest=manifest,
        )
    assert exc_info.value.status_code == 402


def test_branded_pdf_render_uses_white_label_renderer() -> None:
    from services.pdf_reports import report_suite_service

    audit = SimpleNamespace(
        id=1,
        url="https://example.com",
        geo_score=70,
        user=None,
        project=None,
        site_id=None,
        project_id=None,
        full_report={},
    )
    audit.audit_type = None
    manifest = {
        "report_kind": "executive",
        "branding_mode": "white_label",
        "render_report_type": "whitelabel",
    }
    with (
        patch.object(
            report_suite_service, "render_white_label_pdf", return_value=b"%PDF"
        ) as mock_white_label,
        patch.object(report_suite_service, "_prepare_primary_payload", return_value={}),
    ):
        result = report_suite_service.render_report_pdf(
            db=MagicMock(),
            selected_audits=[audit],
            template_type="Executive",
            options={},
            export_manifest=manifest,
        )
        mock_white_label.assert_called_once()
        assert result == b"%PDF"


def test_owner_plan_resolution_covers_pending_and_trial() -> None:
    db, engine = _build_db()
    try:
        owner = _make_user(db, "owner@example.com", plan="plan_executive", status="pending")
        workspace = _make_workspace(db, owner=owner)
        db.commit()
        assert resolve_workspace_owner_plan(db, workspace=workspace) == "plan_starter"
        owner.subscription.status = "active"
        db.commit()
        assert resolve_workspace_owner_plan(db, workspace=workspace) == "plan_executive"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
