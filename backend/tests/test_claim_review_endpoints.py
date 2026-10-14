from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"
os.environ["SSM_ENABLED"] = "false"

import models
from database import Base
from routers.workspace_router import (
    get_audit_claim_review_queue,
    get_audit_claim_review_summary,
    submit_audit_claim_review,
)
from schemas.claim_reviews import ClaimReviewRequest


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
    db.close()
    Base.metadata.drop_all(bind=engine)


def _reviewable_report() -> dict[str, object]:
    return {
        "metadata": {
            "audit_outcome": "completed",
            "track_b_claim_count": 2,
            "integrity_certificate_summary": {
                "track_b_claim_count": 2,
                "needs_manual_review_claims": 2,
            },
            "dual_track_shadow": {
                "summary": {
                    "track_a_claims": 0,
                    "track_b_claims": 2,
                    "mixed_claims": 0,
                    "supported_claims": 0,
                    "flagged_claims": 0,
                    "needs_manual_review_claims": 2,
                    "omitted_claims": 0,
                },
                "track_b_judge": {
                    "enabled": True,
                    "available": True,
                    "evaluated_claims": 2,
                    "needs_manual_review_claims": 2,
                },
                "claims": [
                    {
                        "claim_id": "seo-12",
                        "track": "track_b",
                        "claim_text": "Add entity-backed FAQ blocks to the product pages.",
                        "shadow_disposition": "needs_manual_review",
                        "certainty_score": 0.52,
                        "confidence_band": "contested",
                        "explanation": "Critic could not find enough evidence across the entity graph.",
                        "judge_resolution": "Manual verification required before shipping this recommendation.",
                        "reason_codes": ["unsupported_premise_ref"],
                        "problem_refs": ["seo-problem-1"],
                        "evidence_refs": ["faq-gap"],
                        "suggested_rewrite": "Limit the FAQ recommendation to pages with verified support content.",
                    },
                    {
                        "claim_id": "geo-05",
                        "track": "track_b",
                        "claim_text": "Expand local landing pages for Bucharest and Cluj.",
                        "shadow_disposition": "needs_manual_review",
                        "certainty_score": 0.49,
                        "confidence_band": "contested",
                        "explanation": "The location evidence is partial and still needs human review.",
                        "judge_resolution": "Manual verification required before the location rollout is recommended.",
                        "reason_codes": ["unsupported_location"],
                        "problem_refs": ["geo-problem-2"],
                        "evidence_refs": ["local-gap"],
                        "suggested_rewrite": "Confirm verified service-area coverage before adding city landing pages.",
                    },
                ],
            },
        },
        "debate": {
            "evidence_anchor": {
                "scores": {"seo": 74, "geo": 66, "aeo": 71},
                "critical_metrics": {
                    "pages_crawled": 18,
                    "entity_count": 3,
                    "domain_authority": 34,
                },
                "scan_timestamp": "2026-03-16T10:15:00Z",
            }
        },
        "integrity_certificate": {
            "summary": {
                "total_claims": 2,
                "track_a_total": 0,
                "track_a_supported": 0,
                "track_a_flagged": 0,
                "track_a_omitted": 0,
                "track_b_total": 2,
                "track_b_supported": 0,
                "track_b_flagged": 0,
                "track_b_needs_manual_review": 2,
                "track_b_omitted": 0,
            }
        },
    }


def _seed_workspace(db: Session) -> dict[str, object]:
    owner = models.User(email="owner@example.com", hashed_password="x", role="user", credits=10)
    editor = models.User(email="editor@example.com", hashed_password="x", role="user", credits=0)
    viewer = models.User(email="viewer@example.com", hashed_password="x", role="user", credits=0)
    client = models.User(email="client@example.com", hashed_password="x", role="user", credits=0)
    db.add_all([owner, editor, viewer, client])
    db.flush()

    workspace = models.Workspace(name="Claim Review Ops", owner_id=owner.id)
    db.add(workspace)
    db.flush()

    editor_membership = models.WorkspaceUser(
        workspace_id=workspace.id,
        user_id=editor.id,
        role=models.WorkspaceRole.EDITOR,
    )
    viewer_membership = models.WorkspaceUser(
        workspace_id=workspace.id,
        user_id=viewer.id,
        role=models.WorkspaceRole.VIEWER,
    )
    client_membership = models.WorkspaceUser(
        workspace_id=workspace.id,
        user_id=client.id,
        role=models.WorkspaceRole.CLIENT_READONLY,
    )
    db.add_all([editor_membership, viewer_membership, client_membership])
    db.flush()

    project = models.Project(
        workspace_id=workspace.id,
        name="Northwind",
        domain_url="https://northwind.example",
        language="en",
        target_country="US",
    )
    db.add(project)
    db.flush()

    db.add(
        models.WorkspaceUserProjectAccess(
            workspace_user_id=client_membership.id,
            project_id=project.id,
        )
    )

    audit = models.Audit(
        user_id=owner.id,
        project_id=project.id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url=project.domain_url,
        geo_score=61,
        seo_score=64,
        aeo_score=66,
        full_report=_reviewable_report(),
        created_at=datetime(2026, 3, 16, 10, 30, tzinfo=timezone.utc),
    )
    db.add(audit)
    db.flush()

    db.add_all(
        [
            models.SignalClaimDispositionFact(
                audit_id=audit.id,
                project_id=project.id,
                snapshot_date=datetime(2026, 3, 16, tzinfo=timezone.utc).date(),
                pipeline_type="deep_judgment_delta_flow",
                domain="seo",
                claims_generated=1,
                claims_needs_manual_review=1,
                debate_confidence_score=0.82,
            ),
            models.SignalClaimDispositionFact(
                audit_id=audit.id,
                project_id=project.id,
                snapshot_date=datetime(2026, 3, 16, tzinfo=timezone.utc).date(),
                pipeline_type="deep_judgment_delta_flow",
                domain="geo",
                claims_generated=1,
                claims_needs_manual_review=1,
                debate_confidence_score=0.82,
            ),
        ]
    )
    db.commit()
    db.refresh(owner)
    db.refresh(editor)
    db.refresh(viewer)
    db.refresh(client)
    db.refresh(project)
    db.refresh(audit)

    return {
        "owner": owner,
        "editor": editor,
        "viewer": viewer,
        "client": client,
        "project": project,
        "audit": audit,
    }


def test_claim_review_queue_allows_viewer_and_client_readonly_access() -> None:
    db, engine = _build_db()
    try:
        seeded = _seed_workspace(db)
        viewer = seeded["viewer"]
        client = seeded["client"]
        audit = seeded["audit"]

        viewer_queue = get_audit_claim_review_queue(audit_id=audit.id, user=viewer, db=db)
        assert viewer_queue.total_flagged == 2
        assert viewer_queue.pending == 2
        assert viewer_queue.can_review is False
        assert viewer_queue.claims[0].evidence_anchor_excerpt == {
            "scores": {"seo": 74, "geo": 66, "aeo": 71},
            "critical_metrics": {
                "pages_crawled": 18,
                "entity_count": 3,
                "domain_authority": 34,
            },
            "scan_timestamp": "2026-03-16T10:15:00Z",
        }

        client_queue = get_audit_claim_review_queue(audit_id=audit.id, user=client, db=db)
        assert client_queue.total_flagged == 2
        assert client_queue.can_review is False
    finally:
        _cleanup(db, engine)


def test_claim_review_submit_upserts_and_updates_report_and_signal_facts() -> None:
    db, engine = _build_db()
    try:
        seeded = _seed_workspace(db)
        editor = seeded["editor"]
        audit = seeded["audit"]

        approved = submit_audit_claim_review(
            audit_id=audit.id,
            claim_id="seo-12",
            payload=ClaimReviewRequest(
                disposition="manually_approved",
                note="Validated against the latest content inventory.",
            ),
            user=editor,
            db=db,
        )

        assert approved.review_disposition == "manually_approved"
        assert approved.review_note == "Validated against the latest content inventory."

        db.refresh(audit)
        shadow_claims = audit.full_report["metadata"]["dual_track_shadow"]["claims"]
        seo_claim = next(item for item in shadow_claims if item["claim_id"] == "seo-12")
        assert seo_claim["shadow_disposition"] == "manually_approved"
        assert seo_claim["review_decision"]["reviewed_by_display_name"] == "editor"
        assert (
            audit.full_report["integrity_certificate"]["summary"]["track_b_needs_manual_review"]
            == 1
        )
        assert (
            audit.full_report["integrity_certificate"]["summary"]["track_b_manually_approved"] == 1
        )
        assert (
            audit.full_report["metadata"]["integrity_certificate_summary"][
                "needs_manual_review_claims"
            ]
            == 1
        )

        seo_signal = (
            db.query(models.SignalClaimDispositionFact)
            .filter(
                models.SignalClaimDispositionFact.audit_id == audit.id,
                models.SignalClaimDispositionFact.domain == "seo",
            )
            .one()
        )
        geo_signal = (
            db.query(models.SignalClaimDispositionFact)
            .filter(
                models.SignalClaimDispositionFact.audit_id == audit.id,
                models.SignalClaimDispositionFact.domain == "geo",
            )
            .one()
        )
        assert seo_signal.claims_needs_manual_review == 0
        assert seo_signal.claims_manually_approved == 1
        assert seo_signal.claims_manually_refused == 0
        assert geo_signal.claims_needs_manual_review == 1

        refused = submit_audit_claim_review(
            audit_id=audit.id,
            claim_id="seo-12",
            payload=ClaimReviewRequest(
                disposition="manually_refused",
                note="Recommendation is too broad for the validated support corpus.",
            ),
            user=editor,
            db=db,
        )

        assert refused.id == approved.id
        assert refused.review_disposition == "manually_refused"

        db.refresh(audit)
        seo_claim = next(
            item
            for item in audit.full_report["metadata"]["dual_track_shadow"]["claims"]
            if item["claim_id"] == "seo-12"
        )
        assert seo_claim["shadow_disposition"] == "manually_refused"
        assert audit.full_report["integrity_certificate"]["summary"]["track_b_total"] == 1
        assert (
            audit.full_report["integrity_certificate"]["summary"]["track_b_manually_refused"] == 1
        )
        assert audit.full_report["metadata"]["track_b_claim_count"] == 1

        seo_signal = (
            db.query(models.SignalClaimDispositionFact)
            .filter(
                models.SignalClaimDispositionFact.audit_id == audit.id,
                models.SignalClaimDispositionFact.domain == "seo",
            )
            .one()
        )
        assert seo_signal.claims_needs_manual_review == 0
        assert seo_signal.claims_manually_approved == 0
        assert seo_signal.claims_manually_refused == 1

        summary = get_audit_claim_review_summary(audit_id=audit.id, user=editor, db=db)
        assert summary.total_flagged == 2
        assert summary.approved_count == 0
        assert summary.refused_count == 1
        assert summary.pending_count == 1
        assert summary.impact.export_excluded_claims == 1
    finally:
        _cleanup(db, engine)


def test_claim_review_submit_denies_viewer_and_client() -> None:
    db, engine = _build_db()
    try:
        seeded = _seed_workspace(db)
        viewer = seeded["viewer"]
        client = seeded["client"]
        audit = seeded["audit"]

        for user in (viewer, client):
            with pytest.raises(HTTPException) as exc_info:
                submit_audit_claim_review(
                    audit_id=audit.id,
                    claim_id="geo-05",
                    payload=ClaimReviewRequest(disposition="manually_approved"),
                    user=user,
                    db=db,
                )
            assert exc_info.value.status_code == 403
    finally:
        _cleanup(db, engine)


def test_claim_review_summary_is_empty_when_audit_has_no_reviewable_claims() -> None:
    db, engine = _build_db()
    try:
        seeded = _seed_workspace(db)
        owner = seeded["owner"]
        audit = seeded["audit"]
        audit.full_report = {
            "metadata": {"audit_outcome": "completed", "dual_track_shadow": {"claims": []}},
            "integrity_certificate": {"summary": {"track_b_needs_manual_review": 0}},
        }
        db.commit()

        queue = get_audit_claim_review_queue(audit_id=audit.id, user=owner, db=db)
        summary = get_audit_claim_review_summary(audit_id=audit.id, user=owner, db=db)

        assert queue.total_flagged == 0
        assert queue.claims == []
        assert summary.total_flagged == 0
        assert summary.pending_count == 0
    finally:
        _cleanup(db, engine)
