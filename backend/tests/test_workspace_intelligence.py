"""Tests for AEX-40 Phase 4: Workspace Intelligence Service.

Covers client-health dashboard, invitation tracking, activity logging,
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from services import workspace_intelligence_service as svc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts(days_ago: int = 0) -> datetime:
    """Return a UTC-aware datetime *days_ago* days in the past."""
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


def _make_project(pid: int, name: str, domain: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=pid,
        name=name,
        domain_url=domain,
        workspace_id=1,
        status=models.ProjectStatus.ACTIVE,
    )


def _make_audit(
    aid: int,
    project_id: int,
    seo: float,
    geo: float,
    aeo: float,
    days_ago: int = 0,
    recommendations: list | None = None,
) -> SimpleNamespace:
    report = {}
    if recommendations is not None:
        report["recommendations"] = recommendations
    return SimpleNamespace(
        id=aid,
        project_id=project_id,
        seo_score=seo,
        geo_score=geo,
        aeo_score=aeo,
        full_report=report,
        created_at=_ts(days_ago),
    )


# ===================================================================
# 1. Client-health scores and deltas
# ===================================================================


def test_client_health_scores_and_deltas():
    """Two projects: one with 2 audits (delta), one with 1 (no delta)."""

    proj_a = _make_project(10, "Alpha", "https://alpha.io")
    proj_b = _make_project(20, "Bravo", "https://bravo.io")

    # Project A: two audits — latest (seo=85, geo=70, aeo=60), previous (80, 65, 55)
    audit_a_latest = _make_audit(
        100,
        10,
        seo=85.0,
        geo=70.0,
        aeo=60.0,
        days_ago=1,
        recommendations=["r1", "r2", "r3"],
    )
    audit_a_prev = _make_audit(
        99,
        10,
        seo=80.0,
        geo=65.0,
        aeo=55.0,
        days_ago=10,
    )

    # Project B: single audit
    audit_b = _make_audit(
        200,
        20,
        seo=90.0,
        geo=80.0,
        aeo=75.0,
        days_ago=3,
        recommendations=["r1"],
    )

    db = MagicMock()

    # We need to handle multiple chained query calls.  The service calls
    # db.query(...).filter(...).order_by(...).all()   (projects)
    # db.query(...).filter(...).order_by(...).limit(2).all()  (audits per project)
    # db.query(func.count(...)).filter(...).scalar()  (open approvals)
    #
    # Strategy: track call sequence via side_effect on db.query().

    # Build per-call mock chains
    # Call 1 – projects query
    projects_chain = MagicMock()
    projects_chain.filter.return_value = projects_chain
    projects_chain.order_by.return_value = projects_chain
    projects_chain.all.return_value = [proj_a, proj_b]

    # Call 2 – audits for project A
    audits_a_chain = MagicMock()
    audits_a_chain.filter.return_value = audits_a_chain
    audits_a_chain.order_by.return_value = audits_a_chain
    audits_a_chain.limit.return_value = audits_a_chain
    audits_a_chain.all.return_value = [audit_a_latest, audit_a_prev]

    # Call 3 – open approvals for project A (latest audit id=100)
    approval_a_chain = MagicMock()
    approval_a_chain.filter.return_value = approval_a_chain
    approval_a_chain.scalar.return_value = 2

    # Call 4 – audits for project B
    audits_b_chain = MagicMock()
    audits_b_chain.filter.return_value = audits_b_chain
    audits_b_chain.order_by.return_value = audits_b_chain
    audits_b_chain.limit.return_value = audits_b_chain
    audits_b_chain.all.return_value = [audit_b]

    # Call 5 – open approvals for project B
    approval_b_chain = MagicMock()
    approval_b_chain.filter.return_value = approval_b_chain
    approval_b_chain.scalar.return_value = 0

    db.query.side_effect = [
        projects_chain,  # projects
        audits_a_chain,  # audits for A
        approval_a_chain,  # approvals for A
        audits_b_chain,  # audits for B
        approval_b_chain,  # approvals for B
    ]

    result = svc.get_client_health(db, workspace_id=1)

    assert len(result) == 2

    # --- Project A assertions ---
    a = result[0]
    assert a["project_id"] == 10
    assert a["name"] == "Alpha"
    assert a["latest_seo_score"] == 85.0
    assert a["latest_geo_score"] == 70.0
    assert a["latest_aeo_score"] == 60.0
    # deltas: latest - previous
    assert a["seo_delta"] == 5.0
    assert a["geo_delta"] == 5.0
    assert a["aeo_delta"] == 5.0
    assert a["days_since_last_audit"] == 1
    assert a["recommendation_count"] == 3
    assert a["open_approval_count"] == 2

    # --- Project B assertions (no delta — only 1 audit) ---
    b = result[1]
    assert b["project_id"] == 20
    assert b["latest_seo_score"] == 90.0
    assert b["seo_delta"] is None
    assert b["geo_delta"] is None
    assert b["aeo_delta"] is None
    assert b["days_since_last_audit"] == 3
    assert b["recommendation_count"] == 1
    assert b["open_approval_count"] == 0


# ===================================================================
# 2. Invitation tracking – lifecycle states
# ===================================================================


def test_invitation_tracking_states():
    """create → PENDING, revoke → REVOKED, accept (fresh) → ACCEPTED."""

    db = MagicMock()

    # --- create ---
    inv = svc.create_invitation(
        db,
        workspace_id=1,
        invited_email="alice@example.com",
        invited_name="Alice",
        invited_by_user_id=42,
        role="VIEWER",
        project_ids=[10, 20],
    )

    assert inv.status == models.InvitationStatus.PENDING
    assert inv.token is not None and len(inv.token) > 10
    assert inv.expires_at is not None
    db.add.assert_called()
    db.flush.assert_called()

    # --- revoke ---
    revoked = svc.revoke_invitation(db, invitation=inv)
    assert revoked.status == models.InvitationStatus.REVOKED

    # --- accept a fresh invitation ---
    fresh = svc.create_invitation(
        db,
        workspace_id=1,
        invited_email="bob@example.com",
        invited_name="Bob",
        invited_by_user_id=42,
        role="EDITOR",
        project_ids=None,
    )
    accepted = svc.accept_invitation(db, invitation=fresh)
    assert accepted.status == models.InvitationStatus.ACCEPTED
    assert accepted.accepted_at is not None


# ===================================================================
# 3. Invitation resend – new token
# ===================================================================


def test_invitation_resend_new_token():
    """Resending must replace the token, reset status to PENDING, and
    update expires_at."""

    db = MagicMock()

    inv = svc.create_invitation(
        db,
        workspace_id=1,
        invited_email="carol@example.com",
        invited_name="Carol",
        invited_by_user_id=7,
        role="VIEWER",
        project_ids=None,
    )

    original_token = inv.token
    original_expires = inv.expires_at

    # Small sleep substitute: just call resend (token_urlsafe is random)
    resent = svc.resend_invitation(db, invitation=inv)

    assert resent.token != original_token
    assert resent.status == models.InvitationStatus.PENDING
    # expires_at should be >= original (re-generated from "now")
    assert resent.expires_at >= original_expires


# ===================================================================
# 4. Activity log – member.invited
# ===================================================================


def test_activity_log_member_invite():
    """log_workspace_activity with action='member.invited' persists correctly."""

    db = MagicMock()

    entry = svc.log_workspace_activity(
        db,
        workspace_id=5,
        actor_user_id=42,
        action="member.invited",
        target_type="invitation",
        target_id=99,
        metadata={"email": "new@co.com"},
    )

    assert entry.workspace_id == 5
    assert entry.actor_user_id == 42
    assert entry.action == "member.invited"
    assert entry.target_type == "invitation"
    assert entry.target_id == 99
    assert entry.metadata_json == {"email": "new@co.com"}
    db.add.assert_called_once_with(entry)
    db.flush.assert_called_once()


# ===================================================================
# 5. Activity log – audit.completed
# ===================================================================


def test_activity_log_audit_completed():
    """log_workspace_activity with action='audit.completed' and
    target_type='project'."""

    db = MagicMock()

    entry = svc.log_workspace_activity(
        db,
        workspace_id=3,
        actor_user_id=None,
        action="audit.completed",
        target_type="project",
        target_id=10,
        metadata={"seo_score": 88},
    )

    assert entry.action == "audit.completed"
    assert entry.target_type == "project"
    assert entry.target_id == 10
    assert entry.actor_user_id is None
    assert entry.metadata_json == {"seo_score": 88}
    db.add.assert_called_once()
    db.flush.assert_called_once()


# ===================================================================
# 6. Activity log – pagination and filter
# ===================================================================


def test_activity_log_pagination_and_filter():
    """list_workspace_activity with action_filter returns correct dict shape."""

    fake_items = [SimpleNamespace(id=i, action="audit.completed") for i in range(5)]

    db = MagicMock()
    # The service builds a base_query, then optionally filters, counts,
    # and paginates.  The chain is:
    #   db.query(...).filter(...)          -> base_query
    #   base_query.filter(...)             -> filtered  (action_filter)
    #   filtered.count()                   -> total
    #   filtered.order_by(...).offset(...).limit(...).all() -> items

    base_q = MagicMock()
    db.query.return_value = base_q

    # .filter() for workspace_id
    filtered_q = MagicMock()
    base_q.filter.return_value = filtered_q

    # .filter() for action_filter
    filtered_q2 = MagicMock()
    filtered_q.filter.return_value = filtered_q2

    filtered_q2.count.return_value = 12
    ordered = MagicMock()
    filtered_q2.order_by.return_value = ordered
    offsetted = MagicMock()
    ordered.offset.return_value = offsetted
    limited = MagicMock()
    offsetted.limit.return_value = limited
    limited.all.return_value = fake_items

    result = svc.list_workspace_activity(
        db,
        workspace_id=1,
        action_filter="audit.completed",
        page=2,
        page_size=5,
    )

    assert result["items"] == fake_items
    assert result["total"] == 12
    assert result["page"] == 2
    assert result["page_size"] == 5
