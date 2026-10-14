from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from app.services.billing_retention import subject_email_fingerprint
from auth.security import get_current_user_from_token as get_current_user
from database import Base
from main import app, get_db


def _build_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()

    user = models.User(
        external_id="local_user_123",
        auth_provider="local",
        provider_subject="local_user_123",
        email="privacy@example.com",
        hashed_password="hashed",
        role="admin",
        credits=11,
        notifications_enabled=False,
    )
    target_user = models.User(
        email="target@example.com",
        hashed_password="hashed",
        role="user",
        credits=2,
        notifications_enabled=True,
    )
    db.add_all([user, target_user])
    db.commit()
    db.refresh(user)
    db.refresh(target_user)

    db.add(
        models.Audit(
            user_id=user.id,
            url="https://example.com",
            geo_score=74.2,
            full_report={"summary": "ok"},
            created_at=datetime.now(timezone.utc),
        )
    )
    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id="cus_1",
            stripe_subscription_id="sub_1",
            current_period_end=datetime.now(timezone.utc),
            cancel_at_period_end=True,
            plan_type="plan_specialist",
            status="active",
        )
    )
    db.add(
        models.BillingPayment(
            user_id=user.id,
            stripe_invoice_id="inv_1",
            stripe_customer_id="cus_1",
            stripe_subscription_id="sub_1",
            amount_paid=100,
            amount_due=100,
            currency="usd",
            status="paid",
            hosted_invoice_url="https://invoices.example.com/1",
            invoice_pdf="https://invoices.example.com/1.pdf",
            created_at=datetime.now(timezone.utc),
        )
    )
    db.add(
        models.EmailOutbox(
            user_id=user.id,
            to_email=user.email,
            subject="Welcome",
            html_body="<b>Hello</b>",
            text_body="Hello",
            category="welcome",
            correlation_id="corr_1",
            status="sent",
            provider="resend",
            attempts=1,
        )
    )
    db.add(
        models.UserCreditAdjustment(
            user_id=user.id,
            admin_user_id=user.id,
            delta=5,
            reason="manual grant",
        )
    )
    db.add(
        models.UserCreditAdjustment(
            user_id=target_user.id,
            admin_user_id=user.id,
            delta=3,
            reason="admin help",
        )
    )
    db.add(
        models.AdminActionLog(
            admin_user_id=user.id,
            action="user_credit_update",
            target_type="user",
            target_id=str(user.id),
            metadata_json={"email": user.email},
        )
    )
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    return TestClient(app), db, user, target_user


def test_data_export_and_delete_user_data_flow():
    client, db, user, target_user = _build_client()

    user_id = user.id

    export_response = client.get("/api/v1/users/me/data-export")

    assert export_response.status_code == 200
    export_payload = export_response.json()
    assert export_payload["email"] == user.email
    assert len(export_payload["audits"]) == 1
    assert len(export_payload["billing_payments"]) == 1
    assert len(export_payload["email_outbox"]) == 1
    assert len(export_payload["user_credit_adjustments"]) == 1
    assert len(export_payload["admin_action_logs"]) == 1

    delete_response = client.request(
        "DELETE",
        "/api/v1/users/me",
        json={"confirm": True},
    )

    assert delete_response.status_code == 200
    delete_payload = delete_response.json()
    assert delete_payload["deleted_audits"] == 1
    assert delete_payload["deleted_subscription"] is True
    # SIGV2-1144: this assertion used to read deleted_billing_payments == 1.
    # Deleting the invoice record breaches the UAE retention duty (Cabinet
    # Decision 74/2023 Art. 3, VAT Decree-Law Art. 78), so the old assertion
    # was pinning a compliance defect. The invoice is retained and anonymised.
    assert delete_payload["retained_billing_payments"] == 1
    assert delete_payload["billing_records_retained_until"] is not None
    assert delete_payload["deletion_receipt_reference"]
    assert delete_payload["deleted_email_outbox_entries"] == 1
    assert delete_payload["deleted_user_credit_adjustments"] == 1
    assert delete_payload["anonymized_admin_action_logs"] == 1
    assert delete_payload["anonymized_credit_adjustments_as_admin"] == 1

    assert db.query(models.User).filter(models.User.id == user_id).first() is None
    assert db.query(models.Audit).filter(models.Audit.user_id == user_id).count() == 0
    assert db.query(models.Subscription).filter(models.Subscription.user_id == user_id).count() == 0
    # The invoice row survives with no link to a live account, and is still
    # complete and readable: amounts, currency, status, both Stripe
    # identifiers, the hosted invoice and the PDF are all intact.
    assert (
        db.query(models.BillingPayment).filter(models.BillingPayment.user_id == user_id).count()
        == 0
    )
    retained_invoice = (
        db.query(models.BillingPayment)
        .filter(models.BillingPayment.stripe_invoice_id == "inv_1")
        .one()
    )
    assert retained_invoice.user_id is None
    assert retained_invoice.former_user_id == user_id
    assert retained_invoice.amount_paid == 100
    assert retained_invoice.amount_due == 100
    assert retained_invoice.currency == "usd"
    assert retained_invoice.status == "paid"
    assert retained_invoice.stripe_customer_id == "cus_1"
    assert retained_invoice.stripe_subscription_id == "sub_1"
    assert retained_invoice.hosted_invoice_url == "https://invoices.example.com/1"
    assert retained_invoice.invoice_pdf == "https://invoices.example.com/1.pdf"
    assert retained_invoice.invoice_customer_email == "privacy@example.com"
    assert retained_invoice.retention_until is not None
    assert retained_invoice.anonymized_at is not None

    # The receipt outlives the user row, which is the whole point of it.
    receipt = (
        db.query(models.AccountDeletionReceipt)
        .filter(models.AccountDeletionReceipt.former_user_id == user_id)
        .one()
    )
    assert receipt.reference == delete_payload["deletion_receipt_reference"]
    assert receipt.initiated_by == "self_service"
    assert receipt.retained_billing_payment_count == 1
    assert receipt.subject_email_fingerprint == subject_email_fingerprint("privacy@example.com")
    assert receipt.erased_record_counts["audits"] == 1

    assert db.query(models.EmailOutbox).filter(models.EmailOutbox.user_id == user_id).count() == 0
    assert (
        db.query(models.UserCreditAdjustment)
        .filter(models.UserCreditAdjustment.user_id == user_id)
        .count()
        == 0
    )

    retained_credit_adjustment = (
        db.query(models.UserCreditAdjustment)
        .filter(models.UserCreditAdjustment.user_id == target_user.id)
        .first()
    )
    assert retained_credit_adjustment is not None
    assert retained_credit_adjustment.admin_user_id is None

    retained_admin_log = (
        db.query(models.AdminActionLog)
        .filter(models.AdminActionLog.action == "user_credit_update")
        .first()
    )
    assert retained_admin_log is not None
    assert retained_admin_log.admin_user_id is None
    assert retained_admin_log.metadata_json == {"admin_user_deleted": True}

    app.dependency_overrides.clear()
    db.close()


# ---------------------------------------------------------------------------
# Workspace-aware deletion (SIGV2-1013)
# ---------------------------------------------------------------------------


def _build_workspace_client(*, actor: str = "owner"):
    """Workspace scenario with real FK cascades (PRAGMA foreign_keys=ON)."""
    from sqlalchemy import event

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()

    owner = models.User(
        email="owner@example.com",
        hashed_password="hashed",
        role="user",
        credits=3,
        notifications_enabled=False,
    )
    member = models.User(
        email="member@example.com",
        hashed_password="hashed",
        role="user",
        credits=1,
        notifications_enabled=False,
    )
    db.add_all([owner, member])
    db.commit()
    db.refresh(owner)
    db.refresh(member)

    workspace = models.Workspace(name="Shared Co", owner_id=owner.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    db.add_all(
        [
            models.WorkspaceUser(
                workspace_id=workspace.id,
                user_id=owner.id,
                role=models.WorkspaceRole.ADMIN,
            ),
            models.WorkspaceUser(
                workspace_id=workspace.id,
                user_id=member.id,
                role=models.WorkspaceRole.EDITOR,
            ),
        ]
    )

    project = models.Project(
        workspace_id=workspace.id,
        name="Northwind",
        domain_url="https://northwind.example",
        language="en",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    connection = models.OAuthConnection(
        workspace_id=workspace.id,
        provider=models.OAuthProvider.GOOGLE,
        access_token="access-secret",
        refresh_token="refresh-secret",
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)

    project_connection = models.ProjectOAuthConnection(
        project_id=project.id,
        provider=models.OAuthProvider.GOOGLE,
        access_token="member-access",
        refresh_token="member-refresh",
        connected_by_email=member.email,
    )
    db.add(project_connection)
    db.commit()
    db.refresh(project_connection)

    data_source = models.ProjectDataSource(
        project_id=project.id,
        oauth_connection_id=connection.id,
        project_oauth_connection_id=project_connection.id,
        provider=models.OAuthProvider.GOOGLE,
        source_type=models.ProjectDataSourceType.GOOGLE_ANALYTICS_4,
        source_id="ga4-prop-1",
    )
    db.add(data_source)
    db.commit()
    db.refresh(data_source)

    db.add(
        models.Audit(
            user_id=member.id,
            project_id=project.id,
            project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
            url="https://northwind.example",
            geo_score=50.0,
            full_report={"summary": "member audit"},
            created_at=datetime.now(timezone.utc),
        )
    )
    db.add_all(
        [
            models.UserSession(
                user_id=owner.id,
                token_jti="owner-jti-1",
                is_active=True,
                expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
            ),
            models.UserSession(
                user_id=member.id,
                token_jti="member-jti-1",
                is_active=True,
                expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
            ),
        ]
    )
    db.commit()

    actor_user = owner if actor == "owner" else member

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        return actor_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    client = TestClient(app)
    try:
        yield (
            client,
            db,
            owner,
            member,
            workspace,
            project,
            connection,
            project_connection,
            data_source,
        )
    finally:
        app.dependency_overrides.clear()
        db.close()


def _delete(client):
    return client.request("DELETE", "/api/v1/users/me", json={"confirm": True})


def test_shared_workspace_owner_delete_is_refused_and_member_data_survives():
    for client, db, owner, member, workspace, project, *_ in _build_workspace_client():
        owner_id, member_id, workspace_id, project_id = (
            owner.id,
            member.id,
            workspace.id,
            project.id,
        )
        response = _delete(client)

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "workspace_ownership_transfer_required"

        assert db.get(models.User, owner_id) is not None
        assert db.get(models.Workspace, workspace_id) is not None
        assert db.get(models.Project, project_id) is not None
        assert (
            db.query(models.WorkspaceUser).filter(models.WorkspaceUser.user_id == member_id).count()
            == 1
        )


def test_sole_member_workspace_owner_delete_proceeds():
    for client, db, owner, member, workspace, project, *_ in _build_workspace_client():
        owner_id, member_id, workspace_id, project_id = (
            owner.id,
            member.id,
            workspace.id,
            project.id,
        )
        # Remove the second member so the workspace is sole-member.
        db.query(models.WorkspaceUser).filter(models.WorkspaceUser.user_id == member_id).delete()
        db.commit()

        response = _delete(client)

        assert response.status_code == 200
        db.expire_all()
        assert db.query(models.User).filter_by(id=owner_id).first() is None
        assert db.query(models.Workspace).filter_by(id=workspace_id).first() is None
        assert db.query(models.Project).filter_by(id=project_id).first() is None


def test_member_delete_removes_only_own_membership_and_data():
    for client, db, owner, member, workspace, project, *_ in _build_workspace_client(
        actor="member"
    ):
        owner_id, member_id, workspace_id, project_id = (
            owner.id,
            member.id,
            workspace.id,
            project.id,
        )
        response = _delete(client)

        assert response.status_code == 200
        db.expire_all()
        assert db.query(models.User).filter_by(id=member_id).first() is None
        # Owner's workspace, membership and project are untouched.
        assert db.get(models.User, owner_id) is not None
        assert db.get(models.Workspace, workspace_id) is not None
        assert db.get(models.Project, project_id) is not None
        assert (
            db.query(models.WorkspaceUser).filter(models.WorkspaceUser.user_id == member_id).count()
            == 0
        )
        assert (
            db.query(models.WorkspaceUser).filter(models.WorkspaceUser.user_id == owner_id).count()
            == 1
        )


def test_member_delete_preserves_workspace_oauth_connection(
    monkeypatch,
):
    monkeypatch.setattr("middleware.session_checker.revoke_session_jti", _async_noop, raising=False)
    for (
        client,
        db,
        owner,
        member,
        workspace,
        project,
        connection,
        project_connection,
        data_source,
    ) in _build_workspace_client(actor="member"):
        connection_id, project_connection_id, data_source_id = (
            connection.id,
            project_connection.id,
            data_source.id,
        )
        response = _delete(client)

        assert response.status_code == 200
        db.expire_all()
        # The shared workspace connection is one row per provider with no
        # attribution to who authorised it; it must survive so the remaining
        # members keep their integration.
        surviving_connection = db.query(models.OAuthConnection).filter_by(id=connection_id).first()
        assert surviving_connection is not None
        # The project-level connection is attributable via connected_by_email
        # and is removed; its data source binding degrades via SET NULL.
        assert (
            db.query(models.ProjectOAuthConnection).filter_by(id=project_connection_id).first()
            is None
        )
        surviving = db.query(models.ProjectDataSource).filter_by(id=data_source_id).first()
        assert surviving is not None
        assert surviving.oauth_connection_id == connection_id
        assert surviving.project_oauth_connection_id is None


async def _async_noop(*_args, **_kwargs):
    return None


def test_delete_revokes_user_sessions_and_token_jtis(monkeypatch):
    revoked = []

    async def _record(jti, *args, **kwargs):
        revoked.append(jti)

    monkeypatch.setattr("middleware.session_checker.revoke_session_jti", _record, raising=False)
    for client, db, owner, member, *_ in _build_workspace_client(actor="member"):
        owner_id, member_id = owner.id, member.id
        response = _delete(client)

        assert response.status_code == 200
        db.expire_all()
        assert (
            db.query(models.UserSession).filter(models.UserSession.user_id == member_id).count()
            == 0
        )
        assert "member-jti-1" in revoked
        # Owner's session is untouched.
        assert (
            db.query(models.UserSession).filter(models.UserSession.user_id == owner_id).count() == 1
        )


def test_delete_refused_while_subscription_is_active():
    for client, db, owner, member, *_ in _build_workspace_client():
        owner_id, member_id = owner.id, member.id
        db.query(models.WorkspaceUser).filter(models.WorkspaceUser.user_id == member_id).delete()
        db.add(
            models.Subscription(
                user_id=owner.id,
                stripe_customer_id="cus_1",
                stripe_subscription_id="sub_1",
                current_period_end=datetime.now(timezone.utc),
                cancel_at_period_end=False,
                plan_type="plan_standard",
                status="active",
            )
        )
        db.commit()

        response = _delete(client)

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "active_subscription_cancellation_required"
        assert db.get(models.User, owner_id) is not None

        subscription = (
            db.query(models.Subscription).filter(models.Subscription.user_id == owner_id).first()
        )
        subscription.cancel_at_period_end = True
        db.commit()

        response = _delete(client)
        assert response.status_code == 200
        db.expire_all()
        assert db.query(models.User).filter_by(id=owner_id).first() is None


def test_delete_missing_confirmation_is_rejected():
    for client, db, owner, *_ in _build_workspace_client():
        owner_id = owner.id
        response = client.request("DELETE", "/api/v1/users/me", json={"confirm": False})
        assert response.status_code == 400
        assert db.get(models.User, owner_id) is not None


def test_delete_requires_authentication():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides.pop(get_current_user, None)
    try:
        client = TestClient(app)
        response = _delete(client)
        assert response.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_partial_failure_rolls_back_and_retry_succeeds(monkeypatch):
    for client, db, owner, member, workspace, *_ in _build_workspace_client():
        owner_id, member_id, workspace_id = owner.id, member.id, workspace.id
        db.query(models.WorkspaceUser).filter(models.WorkspaceUser.user_id == member_id).delete()
        db.commit()

        from sqlalchemy.orm import Query

        original_delete = Query.delete
        failed_once = {"done": False}

        def flaky_delete(self, synchronize_session="evaluate"):
            entity = self.column_descriptions[0].get("entity") if self.column_descriptions else None
            if entity is models.EmailOutbox and not failed_once["done"]:
                failed_once["done"] = True
                raise RuntimeError("simulated partial failure")
            return original_delete(self, synchronize_session)

        monkeypatch.setattr(Query, "delete", flaky_delete)

        response = _delete(client)
        assert response.status_code == 500
        # Nothing was committed: user, memberships and workspace all survive.
        assert db.get(models.User, owner_id) is not None
        assert db.get(models.Workspace, workspace_id) is not None
        assert (
            db.query(models.WorkspaceUser).filter(models.WorkspaceUser.user_id == owner_id).count()
            == 1
        )
        db.rollback()

        monkeypatch.setattr(Query, "delete", original_delete)
        response = _delete(client)
        assert response.status_code == 200
        db.expire_all()
        assert db.query(models.User).filter_by(id=owner_id).first() is None


def test_export_includes_workspace_memberships():
    for client, db, owner, member, workspace, project, *_ in _build_workspace_client():
        workspace_id = workspace.id
        response = client.get("/api/v1/users/me/data-export")

        assert response.status_code == 200
        payload = response.json()
        assert "workspaces" in payload
        owned = [w for w in payload["workspaces"] if w["id"] == workspace_id]
        assert owned and owned[0]["is_owner"] is True
