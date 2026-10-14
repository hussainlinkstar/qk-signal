"""Invoice records must outlive account deletion (SIGV2-1144).

`DELETE /api/v1/users/me` used to delete `billing_payments`, which is the
invoice record. The UAE retention duty makes that a breach, not a privacy
measure:

* Cabinet Decision 74/2023 Article 3: 5 years following the Tax Period the
  record relates to, extended by 4 years for a dispute, an ongoing Tax Audit or
  an audit the Authority notified before expiry, and by 1 year from a Voluntary
  Disclosure.
* VAT Decree-Law Article 78: keep all tax invoices issued and received.
* MD 243/2025 Article 11: electronic invoices stay retrievable and reproducible
  in complete and readable form throughout the period.
* GDPR Article 17(3)(b): erasure does not override a legal obligation.

These tests pin: the row survives and stays complete and readable, the receipt
outlives the user row, the admin revenue report still totals correctly with
anonymised rows present, the retention clock runs from the Tax Period and is
extendable, and the deletion still refuses where it refused before.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from app.services.billing_retention import (
    RETENTION_EXTENSION_YEARS,
    TAX_RECORD_RETENTION_YEARS,
    UNNAMED_INVOICE_CUSTOMER,
    effective_retention_until,
    extended_retention_until,
    is_retention_expired,
    retention_until_for_invoice,
    subject_email_fingerprint,
    tax_period_end,
)
from database import Base
from main import app


# ---------------------------------------------------------------------------
# 1. The retention clock
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("invoice_date", "expected_period_end"),
    (
        (datetime(2026, 1, 4, tzinfo=timezone.utc), datetime(2026, 3, 31, tzinfo=timezone.utc)),
        (datetime(2026, 3, 31, tzinfo=timezone.utc), datetime(2026, 3, 31, tzinfo=timezone.utc)),
        (datetime(2026, 5, 17, tzinfo=timezone.utc), datetime(2026, 6, 30, tzinfo=timezone.utc)),
        (datetime(2026, 9, 1, tzinfo=timezone.utc), datetime(2026, 9, 30, tzinfo=timezone.utc)),
        (datetime(2026, 12, 25, tzinfo=timezone.utc), datetime(2026, 12, 31, tzinfo=timezone.utc)),
    ),
)
def test_tax_period_end_is_the_end_of_the_period_the_invoice_relates_to(
    invoice_date: datetime, expected_period_end: datetime
) -> None:
    resolved = tax_period_end(invoice_date)

    assert resolved.date() == expected_period_end.date()
    assert resolved > invoice_date


def test_retention_runs_from_the_tax_period_not_from_the_invoice_date() -> None:
    early_in_quarter = datetime(2026, 1, 2, tzinfo=timezone.utc)
    late_in_quarter = datetime(2026, 3, 20, tzinfo=timezone.utc)

    # Two invoices in the same Tax Period share a retention date: the clock is
    # a property of the period, not an interval from each invoice.
    assert retention_until_for_invoice(early_in_quarter) == retention_until_for_invoice(
        late_in_quarter
    )
    assert retention_until_for_invoice(early_in_quarter).year == (
        early_in_quarter.year + TAX_RECORD_RETENTION_YEARS
    )


def test_retention_is_not_expressed_as_a_fixed_number_of_days() -> None:
    # A fixed interval from the deletion date is the defect this replaces, so
    # the period is expressed in years from a Tax Period end. Across a leap
    # year the elapsed days differ, which a hardcoded day count could not do.
    leap_span = retention_until_for_invoice(
        datetime(2026, 1, 10, tzinfo=timezone.utc)
    ) - tax_period_end(datetime(2026, 1, 10, tzinfo=timezone.utc))
    other_span = retention_until_for_invoice(
        datetime(2027, 1, 10, tzinfo=timezone.utc)
    ) - tax_period_end(datetime(2027, 1, 10, tzinfo=timezone.utc))

    assert leap_span != other_span
    assert TAX_RECORD_RETENTION_YEARS == 5


@pytest.mark.parametrize("reason", ("tax_dispute", "tax_audit", "notified_tax_audit"))
def test_audit_and_dispute_extend_the_period_by_four_years(reason: str) -> None:
    base = retention_until_for_invoice(datetime(2026, 2, 1, tzinfo=timezone.utc))

    extended = extended_retention_until(base, reason)

    assert RETENTION_EXTENSION_YEARS[reason] == 4
    assert extended.year == base.year + 4
    assert extended > base


def test_a_dispute_runs_to_final_settlement_when_that_is_later() -> None:
    base = retention_until_for_invoice(datetime(2026, 2, 1, tzinfo=timezone.utc))
    late_settlement = base.replace(year=base.year + 9)

    assert (
        extended_retention_until(base, "tax_dispute", final_settlement_at=late_settlement)
        == late_settlement
    )


def test_voluntary_disclosure_extends_by_one_year_from_its_submission() -> None:
    base = retention_until_for_invoice(datetime(2026, 2, 1, tzinfo=timezone.utc))
    submitted_at = base.replace(year=base.year + 2)

    extended = extended_retention_until(base, "voluntary_disclosure", event_at=submitted_at)

    assert RETENTION_EXTENSION_YEARS["voluntary_disclosure"] == 1
    assert extended.year == submitted_at.year + 1


def test_unknown_extension_reasons_are_refused() -> None:
    with pytest.raises(ValueError):
        extended_retention_until(datetime.now(timezone.utc), "because_we_felt_like_it")


def test_an_open_hold_keeps_a_row_beyond_its_retention_date() -> None:
    now = datetime(2040, 1, 1, tzinfo=timezone.utc)
    payment = models.BillingPayment(
        stripe_invoice_id="inv_hold",
        stripe_customer_id="cus_hold",
        created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    assert is_retention_expired(payment, now=now) is True

    payment.retention_hold = True
    payment.retention_hold_reason = "tax_audit"
    assert is_retention_expired(payment, now=now) is False


def test_a_row_inside_its_period_is_never_purgeable() -> None:
    created_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
    payment = models.BillingPayment(
        stripe_invoice_id="inv_fresh",
        stripe_customer_id="cus_fresh",
        created_at=created_at,
        retention_until=retention_until_for_invoice(created_at),
    )

    assert is_retention_expired(payment, now=created_at + timedelta(days=365)) is False


def test_rows_predating_the_change_derive_their_retention_date() -> None:
    created_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
    legacy_row = models.BillingPayment(
        stripe_invoice_id="inv_legacy",
        stripe_customer_id="cus_legacy",
        created_at=created_at,
        retention_until=None,
    )

    assert effective_retention_until(legacy_row) == retention_until_for_invoice(created_at)


# ---------------------------------------------------------------------------
# 2. Harness
# ---------------------------------------------------------------------------

INVOICE_CREATED_AT = datetime(2026, 2, 14, 9, 30, tzinfo=timezone.utc)
RETAINED_INVOICE = {
    "stripe_invoice_id": "inv_retained_1",
    "stripe_customer_id": "cus_retained_1",
    "stripe_subscription_id": "sub_retained_1",
    "amount_paid": 39900,
    "amount_due": 39900,
    "currency": "usd",
    "status": "paid",
    "hosted_invoice_url": "https://billing.example/inv_retained_1",
    "invoice_pdf": "https://billing.example/inv_retained_1.pdf",
}


def _build_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):  # pragma: no cover - driver hook
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _seed_customer(db, *, email="paying@example.com", legal_name="Northwind Trading LLC"):
    customer = models.User(
        email=email,
        hashed_password="hashed",
        role="user",
        credits=5,
        notifications_enabled=True,
        company_name="Northwind",
        company_legal_name=legal_name,
        billing_email=email,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)

    db.add(
        models.Subscription(
            user_id=customer.id,
            stripe_customer_id=RETAINED_INVOICE["stripe_customer_id"],
            stripe_subscription_id=RETAINED_INVOICE["stripe_subscription_id"],
            plan_type="plan_specialist",
            status="canceled",
            current_period_end=INVOICE_CREATED_AT,
            cancel_at_period_end=True,
        )
    )
    db.add(
        models.BillingPayment(
            user_id=customer.id,
            created_at=INVOICE_CREATED_AT,
            retention_until=retention_until_for_invoice(INVOICE_CREATED_AT),
            **RETAINED_INVOICE,
        )
    )
    db.commit()
    return customer


def _self_service_client(db, actor: models.User):
    from auth.security import get_current_user_from_token as get_current_user
    from main import get_db

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: actor
    return TestClient(app)


def _admin_client(db, admin_user: models.User):
    from admin import get_current_user as get_current_admin_user
    from admin import get_db as get_admin_db

    def override_get_db():
        yield db

    app.dependency_overrides[get_admin_db] = override_get_db
    app.dependency_overrides[get_current_admin_user] = lambda: admin_user
    return TestClient(app)


def _invoice(db):
    return (
        db.query(models.BillingPayment)
        .filter(models.BillingPayment.stripe_invoice_id == RETAINED_INVOICE["stripe_invoice_id"])
        .one()
    )


# ---------------------------------------------------------------------------
# 3. Self-service deletion
# ---------------------------------------------------------------------------


def test_self_deletion_retains_a_complete_and_readable_invoice(monkeypatch) -> None:
    monkeypatch.setattr("routers.api_router.revoke_session_jti", _async_noop, raising=False)
    db = _build_session()
    try:
        customer = _seed_customer(db)
        customer_id = customer.id
        client = _self_service_client(db, customer)

        response = client.request("DELETE", "/api/v1/users/me", json={"confirm": True})

        assert response.status_code == 200
        payload = response.json()
        assert payload["retained_billing_payments"] == 1
        db.expire_all()

        assert db.query(models.User).filter_by(id=customer_id).first() is None
        assert db.query(models.BillingPayment).count() == 1

        invoice = _invoice(db)
        # Reproducible in complete and readable form: every field that makes
        # the invoice an invoice is still here.
        for field, expected in RETAINED_INVOICE.items():
            assert getattr(invoice, field) == expected
        assert invoice.created_at.replace(tzinfo=timezone.utc) == INVOICE_CREATED_AT
        assert invoice.invoice_customer_name == "Northwind Trading LLC"
        assert invoice.invoice_customer_email == "paying@example.com"
        assert invoice.retention_until is not None

        # The link to a living customer identity is severed.
        assert invoice.user_id is None
        assert invoice.user is None
        assert invoice.former_user_id == customer_id
        assert invoice.anonymized_at is not None
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_self_deletion_leaves_a_receipt_that_outlives_the_user_row(monkeypatch) -> None:
    monkeypatch.setattr("routers.api_router.revoke_session_jti", _async_noop, raising=False)
    db = _build_session()
    try:
        customer = _seed_customer(db)
        customer_id = customer.id
        client = _self_service_client(db, customer)

        response = client.request("DELETE", "/api/v1/users/me", json={"confirm": True})

        assert response.status_code == 200
        reference = response.json()["deletion_receipt_reference"]
        db.expire_all()

        assert db.query(models.User).filter_by(id=customer_id).first() is None
        receipt = db.query(models.AccountDeletionReceipt).one()
        assert receipt.reference == reference
        assert receipt.former_user_id == customer_id
        assert receipt.initiated_by == "self_service"
        assert receipt.initiated_by_admin_user_id is None
        assert receipt.retained_billing_payment_count == 1
        assert receipt.retained_until is not None
        assert receipt.retention_basis
        assert receipt.completed_at is not None
        # The subject is evidenced by a fingerprint, not by keeping the address
        # the request asked us to erase.
        assert receipt.subject_email_fingerprint == subject_email_fingerprint("paying@example.com")
        assert "paying@example.com" not in str(receipt.subject_email_fingerprint)
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_self_deletion_is_still_refused_for_a_shared_workspace_owner() -> None:
    db = _build_session()
    try:
        owner = _seed_customer(db, email="owner@example.com")
        member = models.User(
            email="member@example.com",
            hashed_password="hashed",
            role="user",
            credits=1,
            notifications_enabled=False,
        )
        db.add(member)
        db.commit()
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
        db.commit()

        client = _self_service_client(db, owner)
        response = client.request("DELETE", "/api/v1/users/me", json={"confirm": True})

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "workspace_ownership_transfer_required"
        db.expire_all()
        # Nothing moved: the account is intact and the invoice was not touched.
        assert db.query(models.User).filter_by(id=owner.id).first() is not None
        assert _invoice(db).user_id == owner.id
        assert _invoice(db).anonymized_at is None
        assert db.query(models.AccountDeletionReceipt).count() == 0
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_self_deletion_is_still_refused_while_a_subscription_is_active() -> None:
    db = _build_session()
    try:
        customer = _seed_customer(db, email="active@example.com")
        subscription = (
            db.query(models.Subscription).filter(models.Subscription.user_id == customer.id).one()
        )
        subscription.status = "active"
        subscription.cancel_at_period_end = False
        db.commit()

        client = _self_service_client(db, customer)
        response = client.request("DELETE", "/api/v1/users/me", json={"confirm": True})

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "active_subscription_cancellation_required"
        db.expire_all()
        assert db.query(models.User).filter_by(id=customer.id).first() is not None
        assert _invoice(db).user_id == customer.id
        assert _invoice(db).anonymized_at is None
        assert db.query(models.AccountDeletionReceipt).count() == 0
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_data_export_states_the_retention_date_of_each_invoice() -> None:
    db = _build_session()
    try:
        customer = _seed_customer(db, email="exporter@example.com")
        client = _self_service_client(db, customer)

        response = client.get("/api/v1/users/me/data-export")

        assert response.status_code == 200
        exported = response.json()["billing_payments"]
        assert len(exported) == 1
        assert exported[0]["retention_until"] == (
            retention_until_for_invoice(INVOICE_CREATED_AT).isoformat()
        )
    finally:
        app.dependency_overrides.clear()
        db.close()


# ---------------------------------------------------------------------------
# 4. Admin paths
# ---------------------------------------------------------------------------


def _seed_admin(db) -> models.User:
    admin_user = models.User(
        email="staff@example.com",
        hashed_password="hashed",
        role="admin",
        credits=0,
        notifications_enabled=False,
    )
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)
    return admin_user


def test_admin_user_deletion_retains_the_invoice_and_writes_a_receipt() -> None:
    db = _build_session()
    try:
        admin_user = _seed_admin(db)
        customer = _seed_customer(db, email="admin-deleted@example.com")
        customer_id = customer.id
        client = _admin_client(db, admin_user)

        response = client.delete(f"/api/v1/admin/users/{customer_id}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["deleted"] is True
        assert payload["retained_billing_payments"] == 1
        db.expire_all()

        assert db.query(models.User).filter_by(id=customer_id).first() is None
        invoice = _invoice(db)
        assert invoice.user_id is None
        assert invoice.former_user_id == customer_id
        assert invoice.amount_paid == RETAINED_INVOICE["amount_paid"]

        receipt = db.query(models.AccountDeletionReceipt).one()
        assert receipt.reference == payload["deletion_receipt_reference"]
        assert receipt.initiated_by == "admin"
        assert receipt.initiated_by_admin_user_id == admin_user.id
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_admin_revenue_report_still_totals_correctly_with_anonymised_rows(monkeypatch) -> None:
    monkeypatch.setattr("routers.api_router.revoke_session_jti", _async_noop, raising=False)
    db = _build_session()
    try:
        admin_user = _seed_admin(db)
        customer = _seed_customer(db, email="leaving@example.com")
        staying = models.User(
            email="staying@example.com",
            hashed_password="hashed",
            role="user",
            credits=2,
            notifications_enabled=False,
        )
        db.add(staying)
        db.commit()
        db.refresh(staying)
        db.add(
            models.BillingPayment(
                user_id=staying.id,
                stripe_invoice_id="inv_staying_1",
                stripe_customer_id="cus_staying_1",
                stripe_subscription_id="sub_staying_1",
                amount_paid=9900,
                amount_due=9900,
                currency="usd",
                status="paid",
                created_at=INVOICE_CREATED_AT,
                retention_until=retention_until_for_invoice(INVOICE_CREATED_AT),
            )
        )
        db.commit()

        admin = _admin_client(db, admin_user)
        before = admin.get("/api/v1/admin/billing/invoices")
        assert before.status_code == 200
        before_payload = before.json()
        assert before_payload["total"] == 2
        revenue_before = sum(entry["amount_paid"] for entry in before_payload["invoices"])
        assert revenue_before == 49800

        # The customer deletes their own account.
        app.dependency_overrides.clear()
        self_service = _self_service_client(db, customer)
        assert (
            self_service.request("DELETE", "/api/v1/users/me", json={"confirm": True}).status_code
            == 200
        )
        app.dependency_overrides.clear()
        db.expire_all()

        admin = _admin_client(db, admin_user)
        after = admin.get("/api/v1/admin/billing/invoices")
        assert after.status_code == 200
        after_payload = after.json()

        # Reported revenue did not shrink: this is the accounting hole the
        # inner join used to open.
        assert after_payload["total"] == 2
        assert sum(entry["amount_paid"] for entry in after_payload["invoices"]) == revenue_before

        retained = next(
            entry
            for entry in after_payload["invoices"]
            if entry["stripe_invoice_id"] == RETAINED_INVOICE["stripe_invoice_id"]
        )
        assert retained["user_id"] is None
        assert retained["account_deleted"] is True
        assert retained["user_email"] == "leaving@example.com"
        assert retained["retention_until"] is not None

        # Searching by the address on the invoice still finds it.
        filtered = admin.get("/api/v1/admin/billing/invoices?user_email=leaving@example.com")
        assert filtered.status_code == 200
        assert filtered.json()["total"] == 1
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_admin_gdpr_anonymisation_keeps_the_invoice_recipient_readable() -> None:
    db = _build_session()
    try:
        admin_user = _seed_admin(db)
        customer = _seed_customer(db, email="anonymise-me@example.com")
        client = _admin_client(db, admin_user)

        response = client.post(
            f"/api/v1/admin/gdpr/anonymize/{customer.id}",
            json={"confirm_email": "anonymise-me@example.com"},
        )

        assert response.status_code == 200
        db.expire_all()
        invoice = _invoice(db)
        # The account's own fields are wiped, so without the snapshot the
        # retained invoice could no longer say who it was issued to.
        assert db.query(models.User).filter_by(id=customer.id).one().company_legal_name is None
        assert invoice.invoice_customer_name == "Northwind Trading LLC"
        assert invoice.invoice_customer_email == "anonymise-me@example.com"
        assert invoice.amount_paid == RETAINED_INVOICE["amount_paid"]
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_an_invoice_without_a_named_recipient_still_reports_one(monkeypatch) -> None:
    monkeypatch.setattr("routers.api_router.revoke_session_jti", _async_noop, raising=False)
    db = _build_session()
    try:
        customer = _seed_customer(db, email="sole-trader@example.com", legal_name=None)
        customer.company_name = None
        db.commit()
        client = _self_service_client(db, customer)

        assert (
            client.request("DELETE", "/api/v1/users/me", json={"confirm": True}).status_code == 200
        )
        db.expire_all()

        invoice = _invoice(db)
        assert invoice.invoice_customer_name == UNNAMED_INVOICE_CUSTOMER
        assert invoice.invoice_customer_email == "sole-trader@example.com"
    finally:
        app.dependency_overrides.clear()
        db.close()


# ---------------------------------------------------------------------------
# 5. A retained invoice is never re-attached to a living account
# ---------------------------------------------------------------------------


def test_a_later_stripe_event_does_not_relink_a_retained_invoice() -> None:
    from billing_webhook_worker import _upsert_payment

    db = _build_session()
    try:
        new_customer = _seed_customer(db, email="new-owner@example.com")
        invoice = _invoice(db)
        invoice.user_id = None
        invoice.former_user_id = 4242
        invoice.anonymized_at = datetime.now(timezone.utc)
        db.commit()

        _upsert_payment(
            db,
            user=new_customer,
            invoice={
                "id": RETAINED_INVOICE["stripe_invoice_id"],
                "customer": RETAINED_INVOICE["stripe_customer_id"],
                "subscription": RETAINED_INVOICE["stripe_subscription_id"],
                "amount_paid": 39900,
                "amount_due": 0,
                "currency": "usd",
                "created": int(INVOICE_CREATED_AT.timestamp()),
            },
            status="paid",
        )
        db.commit()
        db.expire_all()

        refreshed = _invoice(db)
        assert refreshed.user_id is None
        assert refreshed.former_user_id == 4242
        # The invoice facts are still refreshed, only the customer link is not.
        assert refreshed.amount_due == 0
    finally:
        db.close()


async def _async_noop(*_args, **_kwargs):
    return None
