import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"
os.environ["DATABASE_URL"] = "postgresql://test:local@localhost:5432/testdb"
os.environ["SSM_ENABLED"] = "0"

import billing_webhook_worker
import models
from database import Base
from routers import api_router


@pytest.fixture(autouse=True)
def _billing_config_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        billing_webhook_worker,
        "load_billing_config",
        lambda db: SimpleNamespace(
            app_base_url="https://app.example.com",
            stripe_mode="test",
            mode_configs={
                "test": SimpleNamespace(secret_key="test-explicit-key"),
                "live": SimpleNamespace(secret_key="live-explicit-key"),
            },
            plan_for_price_id=lambda _price: None,
        ),
    )


def test_stripe_event_log_has_durable_processing_fields_and_indexes() -> None:
    table = models.StripeEventLog.__table__

    assert {
        "claim_token",
        "claimed_at",
        "next_attempt_at",
        "attempt_count",
        "dead_lettered_at",
    } <= set(table.columns.keys())
    assert table.c.attempt_count.default.arg == 0
    assert table.c.attempt_count.server_default.arg == "0"
    assert table.c.claim_token.nullable is True
    assert table.c.claimed_at.nullable is True
    assert table.c.next_attempt_at.nullable is True
    assert table.c.dead_lettered_at.nullable is True
    assert {index.name for index in table.indexes} >= {
        "ix_stripe_event_log_status_next_attempt",
        "ix_stripe_event_log_status_claimed_at",
    }
    assert {constraint.name for constraint in table.constraints} >= {
        "ck_stripe_event_log_attempt_count_nonnegative",
        "ck_stripe_event_log_processing_status",
        "ck_stripe_event_log_state_consistency",
    }
    command_table = models.StripeCommandOutbox.__table__
    assert {constraint.name for constraint in command_table.constraints} >= {
        "ck_stripe_command_outbox_status",
        "ck_stripe_command_outbox_attempt_count_nonnegative",
        "ck_stripe_command_outbox_stripe_mode",
        "ck_stripe_command_outbox_state_consistency",
    }
    assert command_table.c.dead_lettered_at.nullable is True
    assert command_table.c.stripe_mode.nullable is False


def test_split_migrations_are_recoverable_and_match_orm() -> None:
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    names = [
        "20260725_010000_create_top_up_and_stripe_command_tables.py",
        "20260725_011000_add_billing_state_columns.py",
        "20260725_012000_backfill_billing_state.py",
        "20260725_013000_add_billing_state_constraints.py",
        "20260725_014000_validate_billing_state_constraints.py",
        "20260725_015000_finalize_billing_state_not_null.py",
        "20260725_020000_add_stripe_event_due_indexes.py",
        "20260725_021000_add_base_checkout_attempts.py",
        "20260725_022000_add_subscription_user_unique_index.py",
        "20260725_023000_attach_subscription_user_unique_constraint.py",
    ]
    sources = [(versions / name).read_text() for name in names]
    downs = [
        "20260722_150000",
        "20260725_010000",
        "20260725_011000",
        "20260725_012000",
        "20260725_013000",
        "20260725_014000",
        "20260725_015000",
        "20260725_020000",
        "20260725_021000",
        "20260725_022000",
    ]
    for source, down in zip(sources, downs, strict=True):
        assert f'down_revision = "{down}"' in source
    assert "op.create_table" in sources[0]
    assert "op.add_column" not in sources[0] and "UPDATE stripe_event_log" not in sources[0]
    assert "op.add_column" in sources[1] and "UPDATE " not in sources[1]
    assert (
        "_batched_update" in sources[2]
        and "LIMIT 1000" in sources[2]
        and "op.add_column" not in sources[2]
    )
    assert "NOT VALID" in sources[3] and "VALIDATE CONSTRAINT" not in sources[3]
    assert "VALIDATE CONSTRAINT" in sources[4] and "NOT VALID" not in sources[4]
    assert "nullable=False" in sources[5] and "VALIDATE CONSTRAINT" not in sources[5]
    assert "CONCURRENTLY" in sources[6] and "op.create_table" not in sources[6]
    assert "i.indisvalid = false" in sources[6]
    assert "RESET statement_timeout" in sources[6] and "RESET lock_timeout" in sources[6]
    assert "uq_base_checkout_attempts_active_user_mode" in sources[7]
    assert "SUBSCRIPTIONS_USER_ID_DUPLICATES_DETECTED" in sources[8]
    assert "CREATE UNIQUE INDEX CONCURRENTLY" in sources[8]
    assert "UNIQUE USING INDEX" in sources[9]
    assert models.CreditCommitment.stripe_mode.nullable is True


def _build_db() -> tuple[sessionmaker[Session], object]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine), engine


def test_subscription_fence_refreshes_stale_identity_before_customer_validation() -> None:
    factory, engine = _build_db()
    webhook_db = factory()
    updater_db = factory()
    try:
        user = models.User(
            email="stale-subscription-fence@example.com",
            hashed_password="x",
            role="user",
            credits=5,
        )
        webhook_db.add(user)
        webhook_db.flush()
        webhook_db.add(
            models.Subscription(
                user_id=user.id,
                stripe_customer_id="cus_old_fence",
                plan_type="plan_standard",
                status="pending",
            )
        )
        webhook_db.commit()
        stale_user = webhook_db.execute(
            select(models.User).where(models.User.id == user.id)
        ).scalar_one()
        stale_subscription = webhook_db.execute(
            select(models.Subscription).where(models.Subscription.user_id == user.id)
        ).scalar_one()
        assert stale_subscription.stripe_customer_id == "cus_old_fence"

        replacement = updater_db.execute(
            select(models.Subscription).where(models.Subscription.user_id == user.id)
        ).scalar_one()
        replacement.stripe_customer_id = "cus_replacement_fence"
        updater_db.commit()

        with pytest.raises(ValueError, match="subscription_customer_reassignment_rejected"):
            billing_webhook_worker._upsert_subscription(
                webhook_db,
                user=stale_user,
                stripe_customer_id="cus_old_fence",
                stripe_subscription_id="sub_old_fence",
                status="active",
                plan_type="plan_standard",
                current_period_end=None,
                cancel_at_period_end=False,
                stripe_mode="test",
            )
        webhook_db.rollback()

        updater_db.expire_all()
        persisted = updater_db.execute(
            select(models.Subscription).where(models.Subscription.user_id == user.id)
        ).scalar_one()
        assert persisted.stripe_customer_id == "cus_replacement_fence"
        assert persisted.stripe_subscription_id is None
        assert persisted.status == "pending"
    finally:
        webhook_db.close()
        updater_db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _event(
    event_id: str,
    *,
    event_type: str = "test.event",
    livemode: bool = False,
    payload: dict | None = None,
    status: str = "pending",
    claimed_at: datetime | None = None,
    next_attempt_at: datetime | None = None,
    event_created_at: datetime | None = None,
) -> models.StripeEventLog:
    effective_claimed_at = claimed_at
    claim_token = None
    processed_at = None
    dead_lettered_at = None
    effective_payload = dict(payload or {"data": {"object": {}}})
    effective_payload.setdefault("livemode", livemode)
    if status == "processing":
        effective_claimed_at = effective_claimed_at or datetime.now(timezone.utc)
        claim_token = f"claim_{event_id}"
    elif status == "processed":
        processed_at = datetime.now(timezone.utc)
    elif status == "dead_letter":
        dead_lettered_at = datetime.now(timezone.utc)
    return models.StripeEventLog(
        event_id=event_id,
        event_type=event_type,
        event_created_at=event_created_at or datetime.now(timezone.utc),
        payload=effective_payload,
        processing_status=status,
        claim_token=claim_token,
        claimed_at=effective_claimed_at,
        next_attempt_at=next_attempt_at,
        processed_at=processed_at,
        dead_lettered_at=dead_lettered_at,
    )


def _load_event(factory: sessionmaker[Session], event_id: str) -> models.StripeEventLog:
    with factory() as db:
        return db.execute(
            select(models.StripeEventLog).where(models.StripeEventLog.event_id == event_id)
        ).scalar_one()


def test_active_lease_prevents_second_claim() -> None:
    from billing.stripe_event_service import claim_event

    factory, engine = _build_db()
    now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    try:
        with factory() as db:
            db.add(_event("evt_active_lease"))
            db.commit()
        with factory() as first_db:
            first = claim_event(first_db, "evt_active_lease", now=now)
        with factory() as second_db:
            second = claim_event(second_db, "evt_active_lease", now=now + timedelta(seconds=1))

        assert first is not None
        assert second is None
        row = _load_event(factory, "evt_active_lease")
        assert row.attempt_count == 1
        assert row.claim_token == first.claim_token
    finally:
        Base.metadata.drop_all(bind=engine)


def test_stale_lease_is_reclaimed_and_old_token_cannot_complete_or_fail() -> None:
    from billing.stripe_event_service import claim_event, complete_event, fail_event

    factory, engine = _build_db()
    now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    try:
        with factory() as db:
            db.add(_event("evt_stale_lease"))
            db.commit()
        with factory() as db:
            first = claim_event(db, "evt_stale_lease", now=now)
        assert first is not None
        with factory() as db:
            second = claim_event(db, "evt_stale_lease", now=now + timedelta(minutes=6))
        assert second is not None
        assert second.claim_token != first.claim_token

        with factory() as db:
            assert (
                complete_event(
                    db,
                    "evt_stale_lease",
                    first.claim_token,
                    now=now + timedelta(minutes=6, seconds=1),
                )
                is False
            )
        with factory() as db:
            assert (
                fail_event(
                    db,
                    "evt_stale_lease",
                    first.claim_token,
                    RuntimeError("stale owner"),
                    now=now + timedelta(minutes=6, seconds=2),
                )
                is None
            )

        row = _load_event(factory, "evt_stale_lease")
        assert row.processing_status == "processing"
        assert row.claim_token == second.claim_token
        assert row.attempt_count == 2
    finally:
        Base.metadata.drop_all(bind=engine)


def test_expired_claim_cannot_enter_fenced_business_transaction() -> None:
    from billing.stripe_event_service import claim_event, lock_claimed_event

    factory, engine = _build_db()
    claimed_at = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    try:
        with factory() as db:
            db.add(_event("evt_expired_write_fence"))
            db.commit()
        with factory() as db:
            claim = claim_event(db, "evt_expired_write_fence", now=claimed_at)
        assert claim is not None

        with factory() as db:
            assert (
                lock_claimed_event(
                    db,
                    "evt_expired_write_fence",
                    claim.claim_token,
                    now=claimed_at + timedelta(minutes=5),
                )
                is None
            )
    finally:
        Base.metadata.drop_all(bind=engine)


def test_stale_worker_cannot_enter_business_write_section_after_reclaim() -> None:
    from billing.stripe_event_service import (
        claim_event,
        complete_event,
        lock_claimed_event,
    )

    factory, engine = _build_db()
    now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    try:
        with factory() as db:
            user = models.User(
                email="claim-fence@example.com",
                hashed_password="x",
                role="user",
                credits=5,
            )
            db.add(user)
            db.flush()
            user_id = user.id
            db.add(_event("evt_business_fence"))
            db.commit()
        with factory() as db:
            old_claim = claim_event(db, "evt_business_fence", now=now)
        assert old_claim is not None
        with factory() as db:
            new_claim = claim_event(db, "evt_business_fence", now=now + timedelta(minutes=6))
        assert new_claim is not None

        with factory() as old_db:
            old_receipt = lock_claimed_event(
                old_db,
                "evt_business_fence",
                old_claim.claim_token,
                now=now + timedelta(minutes=6),
            )
            if old_receipt is not None:
                old_user = old_db.execute(
                    select(models.User).where(models.User.id == user_id).with_for_update()
                ).scalar_one()
                old_user.credits += 100
            old_db.commit()

        with factory() as new_db:
            new_receipt = lock_claimed_event(
                new_db,
                "evt_business_fence",
                new_claim.claim_token,
                now=now + timedelta(minutes=6, seconds=1),
            )
            assert new_receipt is not None
            new_user = new_db.execute(
                select(models.User).where(models.User.id == user_id).with_for_update()
            ).scalar_one()
            new_user.credits += 10
            assert (
                complete_event(
                    new_db,
                    "evt_business_fence",
                    new_claim.claim_token,
                    now=now + timedelta(minutes=6, seconds=1),
                )
                is True
            )

        with factory() as db:
            assert (
                db.execute(
                    select(models.User.credits).where(models.User.id == user_id)
                ).scalar_one()
                == 15
            )
            receipt = db.execute(
                select(models.StripeEventLog).where(
                    models.StripeEventLog.event_id == "evt_business_fence"
                )
            ).scalar_one()
            assert receipt.processing_status == "processed"
    finally:
        Base.metadata.drop_all(bind=engine)


def test_dead_letter_error_is_sanitized_and_logged_without_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from billing.stripe_event_service import claim_event, fail_event

    factory, engine = _build_db()
    sensitive = "https://private.example/path customer@example.com SELECT confidential_column"
    try:
        with factory() as db:
            db.add(_event("evt_sanitized_dead_letter"))
            db.commit()
        with factory() as db:
            claim = claim_event(db, "evt_sanitized_dead_letter")
        assert claim is not None
        with factory() as db:
            disposition = fail_event(
                db,
                "evt_sanitized_dead_letter",
                claim.claim_token,
                SQLAlchemyError(sensitive),
                max_attempts=1,
            )
        assert disposition is not None
        assert disposition.status == "dead_letter"

        receipt = _load_event(factory, "evt_sanitized_dead_letter")
        error = json.loads(receipt.last_error or "{}")
        assert error == {
            "class": "SQLAlchemyError",
            "code": "database_error",
            "message": "Stripe event database operation failed.",
        }
        assert sensitive not in (receipt.last_error or "")
        assert sensitive not in caplog.text
        assert "evt_sanitized_dead_letter" in caplog.text
    finally:
        Base.metadata.drop_all(bind=engine)


def test_retry_backoff_is_due_gated_and_max_attempts_dead_letters() -> None:
    from billing.stripe_event_service import claim_event, fail_event

    factory, engine = _build_db()
    now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    try:
        with factory() as db:
            db.add(_event("evt_retry"))
            db.commit()

        with factory() as db:
            first = claim_event(db, "evt_retry", now=now)
        assert first is not None
        with factory() as db:
            disposition = fail_event(
                db,
                "evt_retry",
                first.claim_token,
                ValueError("poison payload"),
                now=now,
                max_attempts=3,
            )
        assert disposition is not None
        assert disposition.status == "failed"
        assert disposition.next_attempt_at == now + timedelta(seconds=30)

        with factory() as db:
            assert claim_event(db, "evt_retry", now=now + timedelta(seconds=29)) is None
        with factory() as db:
            second = claim_event(db, "evt_retry", now=now + timedelta(seconds=30))
        assert second is not None
        with factory() as db:
            second_failure = fail_event(
                db,
                "evt_retry",
                second.claim_token,
                ValueError("poison payload"),
                now=now + timedelta(seconds=30),
                max_attempts=3,
            )
        assert second_failure is not None
        assert second_failure.next_attempt_at == now + timedelta(seconds=90)

        with factory() as db:
            third = claim_event(db, "evt_retry", now=now + timedelta(seconds=90))
        assert third is not None
        with factory() as db:
            dead = fail_event(
                db,
                "evt_retry",
                third.claim_token,
                ValueError("poison payload"),
                now=now + timedelta(seconds=90),
                max_attempts=3,
            )
        assert dead is not None
        assert dead.status == "dead_letter"
        row = _load_event(factory, "evt_retry")
        assert row.dead_lettered_at.replace(tzinfo=timezone.utc) == now + timedelta(seconds=90)
        assert row.next_attempt_at is None
        assert row.claim_token is None
    finally:
        Base.metadata.drop_all(bind=engine)


def test_claimed_event_survives_crash_and_becomes_due_after_lease() -> None:
    from billing.stripe_event_service import claim_event, list_due_event_ids

    factory, engine = _build_db()
    now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    try:
        with factory() as db:
            db.add(_event("evt_crash"))
            db.commit()
        with factory() as db:
            claim = claim_event(db, "evt_crash", now=now)
        assert claim is not None

        with factory() as db:
            assert list_due_event_ids(db, now=now + timedelta(minutes=4), limit=10) == []
        with factory() as db:
            assert list_due_event_ids(db, now=now + timedelta(minutes=5), limit=10) == ["evt_crash"]
    finally:
        Base.metadata.drop_all(bind=engine)


def test_due_query_is_bounded_and_excludes_terminal_or_future_work() -> None:
    from billing.stripe_event_service import list_due_event_ids

    factory, engine = _build_db()
    now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    try:
        with factory() as db:
            db.add_all([_event(f"evt_due_{index}") for index in range(5)])
            db.add(_event("evt_future", status="failed", next_attempt_at=now + timedelta(hours=1)))
            db.add(_event("evt_processed", status="processed"))
            db.add(_event("evt_dead", status="dead_letter"))
            db.commit()
        with factory() as db:
            due = list_due_event_ids(db, now=now, limit=3)

        assert len(due) == 3
        assert due == ["evt_due_0", "evt_due_1", "evt_due_2"]
    finally:
        Base.metadata.drop_all(bind=engine)


@pytest.mark.parametrize("terminal_status", ["processed", "dead_letter"])
def test_terminal_events_cannot_be_claimed(terminal_status: str) -> None:
    from billing.stripe_event_service import claim_event

    factory, engine = _build_db()
    try:
        with factory() as db:
            db.add(_event(f"evt_{terminal_status}", status=terminal_status))
            db.commit()
        with factory() as db:
            assert claim_event(db, f"evt_{terminal_status}") is None
    finally:
        Base.metadata.drop_all(bind=engine)


def test_fenced_handler_uses_detached_config_and_email_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, engine = _build_db()
    try:
        user = models.User(
            email="fenced-email@example.com",
            hashed_password="x",
            role="user",
            credits=5,
        )
        with factory() as db:
            db.add(user)
            db.commit()
            db.refresh(user)
            user_id = user.id
            event = _event(
                "evt_fenced_email",
                event_type="invoice.payment_failed",
                payload={
                    "data": {
                        "object": {
                            "id": "in_fenced_email",
                            "customer": "cus_fenced_email",
                            "metadata": {"user_id": str(user_id)},
                            "amount_due": 100,
                            "currency": "usd",
                        }
                    }
                },
            )
            db.add(event)
            db.commit()
            event_id = event.event_id
        with factory() as db:
            db.add(
                models.Subscription(
                    user_id=user_id,
                    stripe_customer_id="cus_fenced_email",
                    plan_type="plan_standard",
                    status="active",
                )
            )
            db.commit()
        monkeypatch.setattr(billing_webhook_worker, "SessionLocal", factory)
        monkeypatch.setattr(
            billing_webhook_worker,
            "load_billing_config",
            lambda db: SimpleNamespace(
                app_base_url="https://app.example.com",
                stripe_mode="test",
                mode_configs={
                    "test": SimpleNamespace(secret_key="test-explicit-key"),
                    "live": SimpleNamespace(secret_key="live-explicit-key"),
                },
                plan_for_price_id=lambda _price: None,
            ),
        )

        def _builder(**kwargs):
            return models.EmailOutbox(
                user_id=kwargs["user_id"],
                to_email=kwargs["to_email"],
                subject="Payment failed",
                text_body="Payment failed",
                category="billing",
                template_key=kwargs["template_key"],
                correlation_id=kwargs["correlation_id"],
                status="pending",
            )

        monkeypatch.setattr(billing_webhook_worker, "_build_email_outbox", _builder)
        asyncio.run(billing_webhook_worker.process_event(event_id))

        row = _load_event(factory, event_id)
        assert row.processing_status == "processed"
        with factory() as db:
            assert db.execute(select(func.count(models.EmailOutbox.id))).scalar_one() == 1
    finally:
        Base.metadata.drop_all(bind=engine)


def test_email_builder_failure_rolls_back_domain_and_event_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, engine = _build_db()
    try:
        with factory() as db:
            user = models.User(
                email="email-rollback@example.com",
                hashed_password="x",
                role="user",
                credits=5,
            )
            db.add(user)
            db.flush()
            user_id = user.id
            db.add(
                models.Subscription(
                    user_id=user_id,
                    stripe_customer_id="cus_email_rollback",
                    plan_type="plan_standard",
                    status="active",
                )
            )
            db.add(
                _event(
                    "evt_email_rollback",
                    event_type="invoice.payment_failed",
                    payload={
                        "data": {
                            "object": {
                                "id": "in_email_rollback",
                                "customer": "cus_email_rollback",
                                "amount_due": 100,
                                "currency": "usd",
                            }
                        }
                    },
                )
            )
            db.commit()
        monkeypatch.setattr(billing_webhook_worker, "SessionLocal", factory)
        monkeypatch.setattr(
            billing_webhook_worker,
            "load_billing_config",
            lambda db: SimpleNamespace(
                app_base_url="https://app.example.com",
                stripe_mode="test",
                mode_configs={
                    "test": SimpleNamespace(secret_key="test-explicit-key"),
                    "live": SimpleNamespace(secret_key="live-explicit-key"),
                },
                plan_for_price_id=lambda _price: None,
            ),
        )
        monkeypatch.setattr(
            billing_webhook_worker,
            "_build_email_outbox",
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("email builder failed")),
        )

        asyncio.run(billing_webhook_worker.process_event("evt_email_rollback"))

        row = _load_event(factory, "evt_email_rollback")
        assert row.processing_status == "failed"
        with factory() as db:
            assert (
                db.execute(
                    select(models.Subscription.status).where(models.Subscription.user_id == user_id)
                ).scalar_one()
                == "active"
            )
            assert db.execute(select(func.count(models.BillingPayment.id))).scalar_one() == 0
    finally:
        Base.metadata.drop_all(bind=engine)


def test_config_snapshot_failure_prevents_domain_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, engine = _build_db()
    try:
        with factory() as db:
            db.add(_event("evt_config_failure"))
            db.commit()
        monkeypatch.setattr(billing_webhook_worker, "SessionLocal", factory)
        monkeypatch.setattr(
            billing_webhook_worker,
            "load_billing_config",
            lambda db: (_ for _ in ()).throw(RuntimeError("config failed")),
        )

        asyncio.run(billing_webhook_worker.process_event("evt_config_failure"))

        row = _load_event(factory, "evt_config_failure")
        assert row.processing_status == "failed"
        assert row.attempt_count == 1
    finally:
        Base.metadata.drop_all(bind=engine)


@pytest.mark.parametrize(
    ("livemode", "expected_mode", "expected_key"),
    [(False, "test", "test-explicit-key"), (True, "live", "live-explicit-key")],
)
def test_event_preparation_uses_receipt_mode_explicit_credential(
    livemode: bool,
    expected_mode: str,
    expected_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from billing.stripe_event_service import claim_event

    factory, engine = _build_db()
    captured: dict[str, object] = {}
    try:
        event_id = f"evt_mode_{expected_mode}"
        with factory() as db:
            db.add(
                _event(
                    event_id,
                    livemode=livemode,
                    event_type="checkout.session.completed",
                    payload={
                        "livemode": livemode,
                        "data": {
                            "object": {
                                "subscription": "sub_mode",
                                "metadata": {"type": "credit_commitment"},
                            }
                        },
                    },
                )
            )
            db.commit()
        with factory() as db:
            claim = claim_event(db, event_id)
        assert claim is not None
        monkeypatch.setattr(billing_webhook_worker, "SessionLocal", factory)
        monkeypatch.setattr(
            billing_webhook_worker,
            "load_billing_config",
            lambda db: SimpleNamespace(
                stripe_mode="live" if not livemode else "test",
                mode_configs={
                    "test": SimpleNamespace(secret_key="test-explicit-key"),
                    "live": SimpleNamespace(secret_key="live-explicit-key"),
                },
            ),
        )

        def _retrieve(subscription_id: str, **kwargs):
            captured.update({"subscription_id": subscription_id, **kwargs})
            return {"id": subscription_id}

        monkeypatch.setattr(billing_webhook_worker.stripe.Subscription, "retrieve", _retrieve)
        prepared = billing_webhook_worker._prepare_event(event_id, claim.claim_token)

        assert prepared is not None
        assert prepared.stripe_mode == expected_mode
        assert captured == {"subscription_id": "sub_mode", "api_key": expected_key}
    finally:
        Base.metadata.drop_all(bind=engine)


def test_stripe_command_outbox_is_idempotent_and_retries_with_same_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from billing.stripe_command_service import enqueue_usage_record_command

    factory, engine = _build_db()
    calls: list[tuple[str, str]] = []
    try:
        with factory() as db:
            first = enqueue_usage_record_command(
                db,
                commitment_id=11,
                cycle_id=22,
                subscription_item_id="si_overage",
                stripe_mode="test",
                quantity=7,
                timestamp=1784980800,
            )
            second = enqueue_usage_record_command(
                db,
                commitment_id=11,
                cycle_id=22,
                subscription_item_id="si_overage",
                stripe_mode="test",
                quantity=7,
                timestamp=1784980800,
            )
            db.commit()
            command_id = first.id
            assert second.id == first.id
        monkeypatch.setattr(billing_webhook_worker, "SessionLocal", factory)
        monkeypatch.setattr(
            billing_webhook_worker,
            "load_billing_config",
            lambda db: SimpleNamespace(
                stripe_mode="live",
                mode_configs={
                    "test": SimpleNamespace(secret_key="test-explicit-key"),
                    "live": SimpleNamespace(secret_key="live-explicit-key"),
                },
            ),
        )

        def _stripe_call(_item_id: str, **kwargs):
            calls.append((str(kwargs["idempotency_key"]), str(kwargs["api_key"])))
            return SimpleNamespace(id="ur_test")

        real_complete = billing_webhook_worker.complete_command
        completion_calls = 0

        def _crash_once(db, claim):
            nonlocal completion_calls
            completion_calls += 1
            if completion_calls == 1:
                raise RuntimeError("crash after Stripe response")
            return real_complete(db, claim)

        monkeypatch.setattr(
            billing_webhook_worker.stripe.SubscriptionItem,
            "create_usage_record",
            _stripe_call,
        )
        monkeypatch.setattr(billing_webhook_worker, "complete_command", _crash_once)

        asyncio.run(billing_webhook_worker.process_stripe_command(command_id))
        with factory() as db:
            command = db.get(models.StripeCommandOutbox, command_id)
            assert command is not None
            assert command.status == "failed"
            command.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        asyncio.run(billing_webhook_worker.process_stripe_command(command_id))

        with factory() as db:
            command = db.get(models.StripeCommandOutbox, command_id)
            assert command is not None
            assert command.status == "succeeded"
            assert command.attempt_count == 2
            assert db.execute(select(func.count(models.StripeCommandOutbox.id))).scalar_one() == 1
        assert calls == [
            ("commitment-overage:11:22", "test-explicit-key"),
            ("commitment-overage:11:22", "test-explicit-key"),
        ]
    finally:
        Base.metadata.drop_all(bind=engine)


def test_missing_command_mode_credential_dead_letters_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from billing.stripe_command_service import enqueue_usage_record_command

    factory, engine = _build_db()
    try:
        with factory() as db:
            command = enqueue_usage_record_command(
                db,
                commitment_id=33,
                cycle_id=44,
                subscription_item_id="si_live_missing",
                stripe_mode="live",
                quantity=1,
                timestamp=1784980800,
            )
            command.attempt_count = 4
            db.commit()
            command_id = command.id
        monkeypatch.setattr(billing_webhook_worker, "SessionLocal", factory)
        monkeypatch.setattr(
            billing_webhook_worker,
            "load_billing_config",
            lambda db: SimpleNamespace(
                stripe_mode="test",
                mode_configs={"test": SimpleNamespace(secret_key="test-explicit-key")},
            ),
        )
        stripe_calls = 0

        def _unexpected_call(*_args, **_kwargs):
            nonlocal stripe_calls
            stripe_calls += 1

        monkeypatch.setattr(
            billing_webhook_worker.stripe.SubscriptionItem,
            "create_usage_record",
            _unexpected_call,
        )

        asyncio.run(billing_webhook_worker.process_stripe_command(command_id))

        with factory() as db:
            command = db.get(models.StripeCommandOutbox, command_id)
            assert command is not None
            assert command.status == "dead_letter"
            assert command.dead_lettered_at is not None
        assert stripe_calls == 0
    finally:
        Base.metadata.drop_all(bind=engine)


def test_handler_db_error_rolls_back_then_persists_retry_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, engine = _build_db()
    try:
        with factory() as db:
            db.add(_event("evt_db_error"))
            db.commit()
        monkeypatch.setattr(billing_webhook_worker, "SessionLocal", factory)

        async def _raise_db_error(_db, _event_log, **_kwargs) -> None:
            raise SQLAlchemyError("simulated handler DB failure")

        monkeypatch.setattr(billing_webhook_worker, "handle_event", _raise_db_error)
        asyncio.run(billing_webhook_worker.process_event("evt_db_error"))

        row = _load_event(factory, "evt_db_error")
        assert row.processing_status == "failed"
        assert row.attempt_count == 1
        assert row.next_attempt_at is not None
        assert json.loads(row.last_error or "{}") == {
            "class": "SQLAlchemyError",
            "code": "database_error",
            "message": "Stripe event database operation failed.",
        }
        assert row.claim_token is None
    finally:
        Base.metadata.drop_all(bind=engine)


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("unknown.event", {"data": {"object": {}}}),
        ("checkout.session.completed", {"data": "malformed"}),
    ],
)
def test_unknown_and_malformed_events_follow_bounded_dead_letter_path(
    event_type: str,
    payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, engine = _build_db()
    now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    event_id = f"evt_poison_{event_type}"
    try:
        with factory() as db:
            db.add(_event(event_id, event_type=event_type, payload=payload))
            db.commit()
        monkeypatch.setattr(billing_webhook_worker, "SessionLocal", factory)

        asyncio.run(
            billing_webhook_worker.process_event(
                event_id,
                now=now,
                max_attempts=2,
            )
        )
        first = _load_event(factory, event_id)
        assert first.processing_status == "failed"

        asyncio.run(
            billing_webhook_worker.process_event(
                event_id,
                now=now + timedelta(seconds=30),
                max_attempts=2,
            )
        )
        dead = _load_event(factory, event_id)
        assert dead.processing_status == "dead_letter"
        assert dead.attempt_count == 2
        assert dead.dead_lettered_at is not None
    finally:
        Base.metadata.drop_all(bind=engine)


def test_timeout_db_poll_recovers_pending_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, engine = _build_db()
    processed: list[str] = []
    try:
        with factory() as db:
            db.add(_event("evt_lost_blpop"))
            db.commit()
        monkeypatch.setattr(billing_webhook_worker, "SessionLocal", factory)

        async def _record(event_id: str, **_kwargs) -> None:
            processed.append(event_id)

        monkeypatch.setattr(billing_webhook_worker, "process_event", _record)
        asyncio.run(billing_webhook_worker.process_due_events(batch_size=10))

        assert processed == ["evt_lost_blpop"]
    finally:
        Base.metadata.drop_all(bind=engine)


def test_poison_redis_wakeup_payload_is_ignored() -> None:
    assert billing_webhook_worker._decode_event_id(b"\xff") is None


@pytest.mark.parametrize(
    ("wakeup", "expected_event_ids"),
    [(None, []), ((b"billing:webhook_events", b"evt_wakeup"), ["evt_wakeup"])],
)
def test_worker_polls_at_startup_and_after_timeout_or_wakeup(
    wakeup: tuple[bytes, bytes] | None,
    expected_event_ids: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    due_polls = 0
    processed: list[str] = []

    class _Redis:
        calls = 0

        async def blpop(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return wakeup
            raise asyncio.CancelledError

        async def delete(self, *_args) -> None:
            return None

        async def aclose(self) -> None:
            return None

    async def _poll_due(**_kwargs) -> int:
        nonlocal due_polls
        due_polls += 1
        return 0

    async def _process(event_id: str, **_kwargs) -> None:
        processed.append(event_id)

    monkeypatch.setattr(billing_webhook_worker, "get_async_redis_client", _Redis)
    monkeypatch.setattr(billing_webhook_worker, "process_due_events", _poll_due)
    monkeypatch.setattr(billing_webhook_worker, "process_due_stripe_commands", _poll_due)
    monkeypatch.setattr(billing_webhook_worker, "process_event", _process)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(billing_webhook_worker.worker_loop())

    assert due_polls == 4
    assert processed == expected_event_ids


def test_webhook_rejects_oversized_content_length_before_streaming() -> None:
    class _Request:
        headers = {"Content-Length": str(api_router.STRIPE_WEBHOOK_MAX_BODY_BYTES + 1)}

        async def stream(self):
            pytest.fail("oversized declared body must not be streamed")
            yield b""

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(api_router._read_stripe_webhook_body(_Request()))

    assert exc_info.value.status_code == 413


def test_webhook_rejects_chunked_body_over_cumulative_limit() -> None:
    class _Request:
        headers: dict[str, str] = {}

        async def stream(self):
            yield b"a" * api_router.STRIPE_WEBHOOK_MAX_BODY_BYTES
            yield b"b"

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(api_router._read_stripe_webhook_body(_Request()))

    assert exc_info.value.status_code == 413


def test_webhook_accepts_exact_body_limit() -> None:
    body = b"a" * api_router.STRIPE_WEBHOOK_MAX_BODY_BYTES

    class _Request:
        headers = {"Content-Length": str(len(body))}

        async def stream(self):
            yield body[:1024]
            yield body[1024:]

    assert asyncio.run(api_router._read_stripe_webhook_body(_Request())) == body


def test_receipt_normalization_excludes_sensitive_and_unexpected_data() -> None:
    from billing.stripe_event_service import normalize_stripe_event_receipt

    receipt = normalize_stripe_event_receipt(
        {
            "id": "evt_normalized",
            "type": "checkout.session.completed",
            "created": 1784980800,
            "livemode": False,
            "data": {
                "object": {
                    "id": "cs_normalized",
                    "object": "checkout.session",
                    "customer": "cus_normalized",
                    "mode": "payment",
                    "payment_status": "paid",
                    "amount_total": 3500,
                    "currency": "usd",
                    "status": "complete",
                    "url": "https://checkout.stripe.com/sensitive",
                    "customer_details": {"email": "customer@example.com"},
                    "payment_method": "pm_sensitive",
                    "metadata": {
                        "type": "base_subscription",
                        "user_id": "42",
                        "plan": "pro",
                        "billing_interval": "month",
                        "unexpected": "must-not-persist",
                    },
                }
            },
        },
        stripe_mode="test",
    )

    serialized = json.dumps(receipt, sort_keys=True)
    assert receipt["data"]["object"]["metadata"] == {
        "type": "base_subscription",
        "user_id": "42",
        "plan": "pro",
        "billing_interval": "month",
    }
    for forbidden in [
        "checkout.stripe.com",
        "customer@example.com",
        "pm_sensitive",
        "must-not-persist",
        "customer_details",
    ]:
        assert forbidden not in serialized


def test_receipt_normalization_preserves_only_base_checkout_metadata() -> None:
    from billing.stripe_event_service import normalize_stripe_event_receipt

    receipt = normalize_stripe_event_receipt(
        {
            "id": "evt_base_checkout",
            "type": "checkout.session.completed",
            "created": 1784980800,
            "livemode": False,
            "data": {
                "object": {
                    "id": "cs_base_checkout",
                    "object": "checkout.session",
                    "customer": "cus_base_checkout",
                    "subscription": "sub_base_checkout",
                    "mode": "subscription",
                    "payment_status": "paid",
                    "status": "complete",
                    "metadata": {
                        "type": "base_subscription",
                        "base_checkout_attempt_id": "bca_opaque_attempt",
                        "user_id": "42",
                        "plan": "plan_standard",
                        "billing_interval": "month",
                        "unexpected": "must-not-persist",
                    },
                }
            },
        },
        stripe_mode="test",
    )

    assert receipt["data"]["object"]["metadata"] == {
        "type": "base_subscription",
        "base_checkout_attempt_id": "bca_opaque_attempt",
        "user_id": "42",
        "plan": "plan_standard",
        "billing_interval": "month",
    }


def test_base_checkout_completion_is_atomic_and_duplicate_safe() -> None:
    from billing import Plan

    factory, engine = _build_db()
    try:
        with factory() as db:
            user = models.User(
                email="base-checkout-webhook@example.com",
                hashed_password="x",
                role="user",
                credits=5,
            )
            db.add(user)
            db.flush()
            attempt = models.BaseCheckoutAttempt(
                id="bca_webhook",
                user_id=user.id,
                stripe_mode="test",
                target_plan=Plan.STANDARD.value,
                billing_interval="month",
                status="customer_created",
                stripe_customer_id="cus_base_webhook",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            db.add(attempt)
            db.add(
                models.Subscription(
                    user_id=user.id,
                    stripe_customer_id="cus_base_webhook",
                    stripe_mode="test",
                    plan_type=Plan.STANDARD.value,
                    status="pending",
                )
            )
            event = _event(
                "evt_base_webhook",
                event_type="checkout.session.completed",
                payload={
                    "data": {
                        "object": {
                            "id": "cs_base_webhook",
                            "object": "checkout.session",
                            "customer": "cus_base_webhook",
                            "subscription": "sub_base_webhook",
                            "client_reference_id": str(user.id),
                            "mode": "subscription",
                            "status": "complete",
                            "metadata": {
                                "type": "base_subscription",
                                "base_checkout_attempt_id": attempt.id,
                                "user_id": str(user.id),
                                "plan": Plan.STANDARD.value,
                                "billing_interval": "month",
                            },
                        }
                    }
                },
            )
            db.add(event)
            db.commit()
            subscription_payload = {
                "id": "sub_base_webhook",
                "customer": "cus_base_webhook",
                "status": "active",
                "current_period_end": 1787572800,
                "cancel_at_period_end": False,
                "items": {
                    "data": [
                        {
                            "price": {
                                "id": "price_base_webhook",
                                "recurring": {"interval": "month"},
                            }
                        }
                    ]
                },
            }
            config = SimpleNamespace(
                app_base_url="https://app.example.com",
                resolve_plan_price=lambda _mode, _price, _interval: Plan.STANDARD,
            )

            asyncio.run(
                billing_webhook_worker.handle_event(
                    db,
                    event,
                    config=config,
                    stripe_mode="test",
                    prepared_subscription_payload=subscription_payload,
                )
            )
            db.commit()
            asyncio.run(
                billing_webhook_worker.handle_event(
                    db,
                    event,
                    config=config,
                    stripe_mode="test",
                    prepared_subscription_payload=subscription_payload,
                )
            )
            db.commit()

            db.refresh(attempt)
            subscription = db.execute(
                select(models.Subscription).where(models.Subscription.user_id == user.id)
            ).scalar_one()
            assert attempt.status == "completed"
            assert attempt.stripe_session_id == "cs_base_webhook"
            assert subscription.status == "active"
            assert subscription.stripe_subscription_id == "sub_base_webhook"
            assert db.execute(select(func.count(models.Subscription.id))).scalar_one() == 1
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _base_checkout_rollover_payloads(
    *,
    user_id: int,
    attempt_id: str,
    customer_id: str = "cus_base_rollover",
    session_id: str = "cs_base_rollover",
    subscription_id: str = "sub_base_rollover_new",
    session_status: str = "complete",
    subscription_status: str = "active",
) -> tuple[dict, dict]:
    metadata = {
        "type": "base_subscription",
        "base_checkout_attempt_id": attempt_id,
        "user_id": str(user_id),
        "plan": "plan_specialist",
        "billing_interval": "year",
    }
    session = {
        "id": session_id,
        "object": "checkout.session",
        "customer": customer_id,
        "subscription": subscription_id,
        "client_reference_id": str(user_id),
        "mode": "subscription",
        "status": session_status,
        "metadata": metadata,
    }
    subscription = {
        "id": subscription_id,
        "object": "subscription",
        "customer": customer_id,
        "status": subscription_status,
        "current_period_end": 1819012800,
        "cancel_at_period_end": False,
        "items": {
            "data": [
                {
                    "price": {
                        "id": "price_base_rollover_specialist_year",
                        "recurring": {"interval": "year"},
                    }
                }
            ]
        },
    }
    return session, subscription


@pytest.mark.parametrize("old_status", ["canceled", "incomplete_expired"])
def test_validated_base_checkout_atomically_rolls_over_terminal_subscription_and_is_idempotent(
    old_status: str,
) -> None:
    from billing import Plan

    factory, engine = _build_db()
    event_created_at = datetime(2026, 7, 28, 18, 0, tzinfo=timezone.utc)
    try:
        with factory() as db:
            user = models.User(
                email=f"base-rollover-{old_status}@example.com",
                hashed_password="x",
                role="user",
                credits=5,
            )
            db.add(user)
            db.flush()
            attempt = models.BaseCheckoutAttempt(
                id=f"bca_rollover_{old_status}",
                user_id=user.id,
                stripe_mode="test",
                target_plan=Plan.SPECIALIST.value,
                billing_interval="year",
                status="session_created",
                stripe_customer_id="cus_base_rollover",
                stripe_session_id="cs_base_rollover",
                expires_at=event_created_at + timedelta(hours=1),
            )
            subscription = models.Subscription(
                user_id=user.id,
                stripe_customer_id="cus_base_rollover",
                stripe_subscription_id="sub_base_rollover_old",
                stripe_mode="test",
                plan_type=Plan.STANDARD.value,
                status=old_status,
                billing_interval="month",
                current_period_end=event_created_at - timedelta(days=1),
                cancel_at_period_end=True,
                stripe_schedule_id="sub_sched_obsolete_pending",
                managed_plan_change_schedule_id="sub_sched_obsolete_managed",
                pending_plan_type=Plan.STARTER.value,
                pending_billing_interval="month",
                pending_change_effective_at=event_created_at + timedelta(days=10),
                plan_state_event_created_at=event_created_at - timedelta(days=30),
            )
            db.add_all([attempt, subscription])
            db.commit()

            session, subscription_payload = _base_checkout_rollover_payloads(
                user_id=user.id,
                attempt_id=attempt.id,
            )
            event = _event(
                f"evt_base_rollover_{old_status}",
                event_type="checkout.session.completed",
                event_created_at=event_created_at,
                payload={"livemode": False, "data": {"object": session}},
            )
            config = SimpleNamespace(
                app_base_url="https://app.example.com",
                resolve_plan_price=lambda mode, price, interval: (
                    Plan.SPECIALIST
                    if (
                        mode,
                        price,
                        interval,
                    )
                    == (
                        "test",
                        "price_base_rollover_specialist_year",
                        "year",
                    )
                    else None
                ),
            )

            asyncio.run(
                billing_webhook_worker.handle_event(
                    db,
                    event,
                    config=config,
                    stripe_mode="test",
                    prepared_subscription_payload=subscription_payload,
                )
            )
            first_state = {
                field: getattr(subscription, field)
                for field in (
                    "stripe_customer_id",
                    "stripe_subscription_id",
                    "stripe_mode",
                    "plan_type",
                    "status",
                    "billing_interval",
                    "current_period_end",
                    "cancel_at_period_end",
                    "stripe_schedule_id",
                    "managed_plan_change_schedule_id",
                    "pending_plan_type",
                    "pending_billing_interval",
                    "pending_change_effective_at",
                    "plan_state_event_created_at",
                )
            }
            asyncio.run(
                billing_webhook_worker.handle_event(
                    db,
                    event,
                    config=config,
                    stripe_mode="test",
                    prepared_subscription_payload=subscription_payload,
                )
            )
            second_state = {field: getattr(subscription, field) for field in first_state}
            db.commit()

            db.refresh(attempt)
            db.refresh(subscription)
            assert attempt.status == "completed"
            assert attempt.stripe_session_id == "cs_base_rollover"
            assert subscription.stripe_subscription_id == "sub_base_rollover_new"
            assert subscription.stripe_customer_id == "cus_base_rollover"
            assert subscription.stripe_mode == "test"
            assert subscription.plan_type == Plan.SPECIALIST.value
            assert subscription.billing_interval == "year"
            assert subscription.status == "active"
            assert subscription.cancel_at_period_end is False
            assert subscription.stripe_schedule_id is None
            assert subscription.managed_plan_change_schedule_id is None
            assert subscription.pending_plan_type is None
            assert subscription.pending_billing_interval is None
            assert subscription.pending_change_effective_at is None
            assert subscription.plan_state_event_created_at is not None
            assert (
                subscription.plan_state_event_created_at.replace(tzinfo=timezone.utc)
                == event_created_at
            )
            assert second_state == first_state
            assert db.execute(select(func.count(models.Subscription.id))).scalar_one() == 1
            assert db.execute(select(func.count(models.BaseCheckoutAttempt.id))).scalar_one() == 1
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.parametrize(
    "case",
    [
        "nonterminal_old_status",
        "customer_mismatch",
        "mode_mismatch",
        "missing_attempt",
        "invalid_attempt",
        "unvalidated_session",
        "unvalidated_subscription",
    ],
)
def test_base_checkout_rollover_rejects_unvalidated_or_ineligible_transition(
    case: str,
) -> None:
    from billing import Plan
    from billing.base_checkout_service import BaseCheckoutError

    factory, engine = _build_db()
    event_created_at = datetime(2026, 7, 28, 19, 0, tzinfo=timezone.utc)
    try:
        with factory() as db:
            user = models.User(
                email=f"base-rollover-reject-{case}@example.com",
                hashed_password="x",
                role="user",
                credits=5,
            )
            db.add(user)
            db.flush()
            attempt_id = f"bca_rollover_reject_{case}"
            attempt = None
            if case != "missing_attempt":
                attempt = models.BaseCheckoutAttempt(
                    id=attempt_id,
                    user_id=user.id,
                    stripe_mode="test",
                    target_plan=Plan.SPECIALIST.value,
                    billing_interval="year",
                    status="canceled" if case == "invalid_attempt" else "session_created",
                    stripe_customer_id=(
                        "cus_base_rollover_other"
                        if case == "customer_mismatch"
                        else "cus_base_rollover"
                    ),
                    stripe_session_id="cs_base_rollover",
                    expires_at=event_created_at + timedelta(hours=1),
                )
                db.add(attempt)
            subscription = models.Subscription(
                user_id=user.id,
                stripe_customer_id="cus_base_rollover",
                stripe_subscription_id="sub_base_rollover_old",
                stripe_mode="live" if case == "mode_mismatch" else "test",
                plan_type=Plan.STANDARD.value,
                status="active" if case == "nonterminal_old_status" else "canceled",
                billing_interval="month",
                current_period_end=event_created_at - timedelta(days=1),
                cancel_at_period_end=True,
                stripe_schedule_id="sub_sched_reject_pending",
                managed_plan_change_schedule_id="sub_sched_reject_managed",
                pending_plan_type=Plan.STARTER.value,
                pending_billing_interval="month",
                pending_change_effective_at=event_created_at + timedelta(days=10),
                plan_state_event_created_at=event_created_at - timedelta(days=30),
            )
            db.add(subscription)
            db.commit()
            original_subscription = {
                field: getattr(subscription, field)
                for field in (
                    "stripe_customer_id",
                    "stripe_subscription_id",
                    "stripe_mode",
                    "plan_type",
                    "status",
                    "billing_interval",
                    "current_period_end",
                    "cancel_at_period_end",
                    "stripe_schedule_id",
                    "managed_plan_change_schedule_id",
                    "pending_plan_type",
                    "pending_billing_interval",
                    "pending_change_effective_at",
                    "plan_state_event_created_at",
                )
            }
            original_attempt_status = attempt.status if attempt is not None else None
            customer_id = (
                "cus_base_rollover_other" if case == "customer_mismatch" else "cus_base_rollover"
            )
            session, subscription_payload = _base_checkout_rollover_payloads(
                user_id=user.id,
                attempt_id=attempt_id,
                customer_id=customer_id,
                session_status="open" if case == "unvalidated_session" else "complete",
                subscription_status=(
                    "incomplete" if case == "unvalidated_subscription" else "active"
                ),
            )
            event = _event(
                f"evt_base_rollover_reject_{case}",
                event_type="checkout.session.completed",
                event_created_at=event_created_at,
                payload={"livemode": False, "data": {"object": session}},
            )
            config = SimpleNamespace(
                app_base_url="https://app.example.com",
                resolve_plan_price=lambda _mode, _price, _interval: Plan.SPECIALIST,
            )

            with pytest.raises((ValueError, BaseCheckoutError)):
                asyncio.run(
                    billing_webhook_worker.handle_event(
                        db,
                        event,
                        config=config,
                        stripe_mode="test",
                        prepared_subscription_payload=subscription_payload,
                    )
                )
            db.rollback()
            db.expire_all()

            persisted_subscription = db.execute(select(models.Subscription)).scalar_one()
            assert {
                field: getattr(persisted_subscription, field) for field in original_subscription
            } == original_subscription
            if attempt is not None:
                persisted_attempt = db.get(models.BaseCheckoutAttempt, attempt_id)
                assert persisted_attempt is not None
                assert persisted_attempt.status == original_attempt_status
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_ordinary_subscription_webhook_cannot_rebind_terminal_subscription_identity() -> None:
    from billing import Plan

    factory, engine = _build_db()
    try:
        with factory() as db:
            user = models.User(
                email="ordinary-webhook-terminal-rebind@example.com",
                hashed_password="x",
                role="user",
                credits=5,
            )
            db.add(user)
            db.flush()
            subscription = models.Subscription(
                user_id=user.id,
                stripe_customer_id="cus_terminal_identity",
                stripe_subscription_id="sub_terminal_old",
                stripe_mode="test",
                plan_type=Plan.STANDARD.value,
                status="canceled",
                billing_interval="month",
            )
            db.add(subscription)
            db.commit()
            event = _event(
                "evt_ordinary_terminal_rebind",
                event_type="customer.subscription.updated",
                payload={
                    "livemode": False,
                    "data": {
                        "object": {
                            "id": "sub_terminal_new",
                            "object": "subscription",
                            "customer": "cus_terminal_identity",
                            "status": "active",
                            "items": {
                                "data": [
                                    {
                                        "price": {
                                            "id": "price_terminal_new",
                                            "recurring": {"interval": "year"},
                                        }
                                    }
                                ]
                            },
                        }
                    },
                },
            )
            config = SimpleNamespace(
                app_base_url="https://app.example.com",
                commitment_tier_for_price_id=lambda _price_id: None,
                resolve_plan_price=lambda _mode, _price, _interval: Plan.SPECIALIST,
            )

            with pytest.raises(ValueError, match="subscription_id_reassignment_rejected"):
                asyncio.run(
                    billing_webhook_worker.handle_event(
                        db,
                        event,
                        config=config,
                        stripe_mode="test",
                    )
                )
            db.rollback()
            db.refresh(subscription)

            assert subscription.stripe_subscription_id == "sub_terminal_old"
            assert subscription.status == "canceled"
            assert subscription.plan_type == Plan.STANDARD.value
            assert subscription.billing_interval == "month"
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_base_checkout_completion_heals_pristine_pending_attempt() -> None:
    from billing import Plan
    from billing.base_checkout_service import BaseCheckoutValidationError
    from billing.stripe_event_service import normalize_stripe_event_receipt

    factory, engine = _build_db()
    try:
        with factory() as db:
            user = models.User(
                email="base-checkout-crash-healing@example.com",
                hashed_password="x",
                role="user",
                credits=5,
            )
            db.add(user)
            db.flush()
            attempt = models.BaseCheckoutAttempt(
                id="bca_crash_healing",
                user_id=user.id,
                stripe_mode="test",
                target_plan=Plan.STANDARD.value,
                billing_interval="month",
                status="pending",
                expires_at=datetime(2026, 7, 25, 13, 0, tzinfo=timezone.utc),
            )
            db.add(attempt)
            db.commit()
            assert attempt.stripe_customer_id is None
            assert attempt.stripe_session_id is None
            assert db.execute(select(models.Subscription)).scalars().all() == []

            metadata = {
                "type": "base_subscription",
                "base_checkout_attempt_id": attempt.id,
                "user_id": str(user.id),
                "plan": Plan.STANDARD.value,
                "billing_interval": "month",
            }
            receipt = normalize_stripe_event_receipt(
                {
                    "id": "evt_crash_healing",
                    "type": "checkout.session.completed",
                    "created": 1784980800,
                    "livemode": False,
                    "data": {
                        "object": {
                            "id": "cs_crash_healing",
                            "object": "checkout.session",
                            "customer": "cus_crash_healing",
                            "subscription": "sub_crash_healing",
                            "client_reference_id": str(user.id),
                            "mode": "subscription",
                            "payment_status": "paid",
                            "status": "complete",
                            "metadata": metadata,
                        }
                    },
                },
                stripe_mode="test",
            )
            event = _event(
                "evt_crash_healing",
                event_type="checkout.session.completed",
                payload=receipt,
            )
            db.add(event)
            db.commit()
            subscription_payload = {
                "id": "sub_crash_healing",
                "object": "subscription",
                "customer": "cus_crash_healing",
                "status": "trialing",
                "livemode": False,
                "metadata": metadata,
                "items": {
                    "data": [
                        {
                            "price": {
                                "id": "price_crash_healing",
                                "recurring": {"interval": "month"},
                            }
                        }
                    ]
                },
            }
            config = SimpleNamespace(
                app_base_url="https://app.example.com",
                resolve_plan_price=lambda _mode, _price, _interval: Plan.STANDARD,
            )

            asyncio.run(
                billing_webhook_worker.handle_event(
                    db,
                    event,
                    config=config,
                    stripe_mode="test",
                    prepared_subscription_payload=subscription_payload,
                )
            )
            db.commit()

            db.refresh(attempt)
            subscriptions = (
                db.execute(
                    select(models.Subscription).where(models.Subscription.user_id == user.id)
                )
                .scalars()
                .all()
            )
            assert attempt.status == "completed"
            assert attempt.stripe_customer_id == "cus_crash_healing"
            assert attempt.stripe_session_id == "cs_crash_healing"
            assert len(subscriptions) == 1
            assert subscriptions[0].stripe_customer_id == "cus_crash_healing"
            assert subscriptions[0].stripe_subscription_id == "sub_crash_healing"
            assert subscriptions[0].status == "trialing"

            mismatched_attempt = models.BaseCheckoutAttempt(
                id="bca_customer_mismatch",
                user_id=user.id,
                stripe_mode="test",
                target_plan=Plan.STANDARD.value,
                billing_interval="month",
                status="customer_created",
                stripe_customer_id="cus_different",
                expires_at=datetime(2026, 7, 25, 14, 0, tzinfo=timezone.utc),
            )
            db.add(mismatched_attempt)
            db.commit()
            mismatch_metadata = {
                **metadata,
                "base_checkout_attempt_id": mismatched_attempt.id,
            }
            mismatch_event = _event(
                "evt_customer_mismatch",
                event_type="checkout.session.completed",
                payload={
                    "livemode": False,
                    "data": {
                        "object": {
                            "id": "cs_customer_mismatch",
                            "object": "checkout.session",
                            "customer": "cus_crash_healing",
                            "subscription": "sub_customer_mismatch",
                            "client_reference_id": str(user.id),
                            "mode": "subscription",
                            "status": "complete",
                            "metadata": mismatch_metadata,
                        }
                    },
                },
            )
            mismatch_subscription = {
                **subscription_payload,
                "id": "sub_customer_mismatch",
                "metadata": mismatch_metadata,
            }

            with pytest.raises(BaseCheckoutValidationError, match="customer does not match"):
                asyncio.run(
                    billing_webhook_worker.handle_event(
                        db,
                        mismatch_event,
                        config=config,
                        stripe_mode="test",
                        prepared_subscription_payload=mismatch_subscription,
                    )
                )
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_delayed_completed_session_wins_over_elapsed_local_attempt_time() -> None:
    from billing import Plan
    from billing.base_checkout_service import resolve_base_checkout_attempt

    factory, engine = _build_db()
    try:
        with factory() as db:
            user = models.User(
                email="delayed-base-checkout@example.com",
                hashed_password="x",
                role="user",
                credits=5,
            )
            db.add(user)
            db.flush()
            attempt = models.BaseCheckoutAttempt(
                id="bca_delayed_completion",
                user_id=user.id,
                stripe_mode="test",
                target_plan=Plan.STANDARD.value,
                billing_interval="month",
                status="session_created",
                stripe_customer_id="cus_delayed_completion",
                stripe_session_id="cs_delayed_completion",
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
            db.add(attempt)
            db.commit()

            replay = resolve_base_checkout_attempt(
                db,
                user_id=user.id,
                stripe_mode="test",
                target_plan=Plan.STANDARD.value,
                billing_interval="month",
                now=datetime.now(timezone.utc),
            )

            event = _event(
                "evt_delayed_base_completion",
                event_type="checkout.session.completed",
                payload={
                    "data": {
                        "object": {
                            "id": "cs_delayed_completion",
                            "object": "checkout.session",
                            "customer": "cus_delayed_completion",
                            "subscription": "sub_delayed_completion",
                            "client_reference_id": str(user.id),
                            "mode": "subscription",
                            "status": "complete",
                            "metadata": {
                                "type": "base_subscription",
                                "base_checkout_attempt_id": attempt.id,
                                "user_id": str(user.id),
                                "plan": Plan.STANDARD.value,
                                "billing_interval": "month",
                            },
                        }
                    }
                },
            )
            db.add(event)
            db.commit()
            subscription_payload = {
                "id": "sub_delayed_completion",
                "customer": "cus_delayed_completion",
                "status": "active",
                "items": {
                    "data": [
                        {
                            "price": {
                                "id": "price_delayed_completion",
                                "recurring": {"interval": "month"},
                            }
                        }
                    ]
                },
            }
            config = SimpleNamespace(
                app_base_url="https://app.example.com",
                resolve_plan_price=lambda _mode, _price, _interval: Plan.STANDARD,
            )

            asyncio.run(
                billing_webhook_worker.handle_event(
                    db,
                    event,
                    config=config,
                    stripe_mode="test",
                    prepared_subscription_payload=subscription_payload,
                )
            )
            db.commit()

            db.refresh(attempt)
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert replay.created is False
            assert replay.attempt.id == attempt.id
            assert db.execute(select(func.count(models.BaseCheckoutAttempt.id))).scalar_one() == 1
            assert attempt.status == "completed"
            assert subscription.user_id == user.id
            assert subscription.stripe_subscription_id == "sub_delayed_completion"
            assert subscription.status == "active"
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_receipt_normalization_preserves_supported_handler_fields() -> None:
    from billing.stripe_event_service import normalize_stripe_event_receipt

    subscription = normalize_stripe_event_receipt(
        {
            "id": "evt_subscription_fields",
            "type": "customer.subscription.updated",
            "created": 1784980800,
            "livemode": False,
            "data": {
                "object": {
                    "id": "sub_fields",
                    "object": "subscription",
                    "customer": "cus_fields",
                    "status": "active",
                    "current_period_start": 1784980800,
                    "current_period_end": 1787572800,
                    "cancel_at_period_end": False,
                    "schedule": "sub_sched_fields",
                    "metadata": {"user_id": "42", "unexpected": "drop"},
                    "items": {
                        "data": [
                            {
                                "id": "si_fields",
                                "price": {
                                    "id": "price_fields",
                                    "recurring": {"interval": "month"},
                                },
                            }
                        ]
                    },
                }
            },
        },
        stripe_mode="test",
    )
    invoice = normalize_stripe_event_receipt(
        {
            "id": "evt_invoice_fields",
            "type": "invoice.paid",
            "created": 1784980800,
            "livemode": False,
            "data": {
                "object": {
                    "id": "in_fields",
                    "object": "invoice",
                    "customer": "cus_fields",
                    "subscription": "sub_fields",
                    "status": "paid",
                    "paid": True,
                    "amount_paid": 3500,
                    "amount_due": 3500,
                    "currency": "usd",
                    "period_start": 1784980800,
                    "period_end": 1787572800,
                    "hosted_invoice_url": "https://private.example/invoice",
                    "invoice_pdf": "https://private.example/invoice.pdf",
                    "lines": {
                        "data": [
                            {
                                "price": {
                                    "id": "price_fields",
                                    "recurring": {"interval": "month"},
                                },
                                "period": {"start": 1784980800, "end": 1787572800},
                            }
                        ]
                    },
                }
            },
        },
        stripe_mode="test",
    )

    subscription_object = subscription["data"]["object"]
    assert subscription_object["items"]["data"][0]["id"] == "si_fields"
    assert subscription_object["schedule"] == "sub_sched_fields"
    assert subscription_object["metadata"] == {"user_id": "42"}
    invoice_object = invoice["data"]["object"]
    assert invoice_object["lines"]["data"][0]["period"]["end"] == 1787572800
    assert "hosted_invoice_url" not in invoice_object
    assert "invoice_pdf" not in invoice_object


def test_receipt_rejects_supported_event_object_mismatch() -> None:
    from billing.stripe_event_service import normalize_stripe_event_receipt

    with pytest.raises(ValueError, match="stripe_event_object_mismatch"):
        normalize_stripe_event_receipt(
            {
                "id": "evt_wrong_pair",
                "type": "invoice.paid",
                "created": 1784980800,
                "livemode": False,
                "data": {"object": {"id": "cs_wrong", "object": "checkout.session"}},
            },
            stripe_mode="test",
        )


def test_unknown_event_receipt_retains_only_minimal_object_identity() -> None:
    from billing.stripe_event_service import normalize_stripe_event_receipt

    receipt = normalize_stripe_event_receipt(
        {
            "id": "evt_unknown_minimal",
            "type": "future.event.type",
            "created": 1784980800,
            "livemode": False,
            "data": {
                "object": {
                    "id": "obj_unknown",
                    "object": "future.object",
                    "email": "customer@example.com",
                    "metadata": {"secret": "unexpected"},
                }
            },
        },
        stripe_mode="test",
    )

    assert receipt["data"]["object"] == {
        "id": "obj_unknown",
        "object": "future.object",
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"livemode": True},
        {"created": True},
        {"created": 0},
        {"created": 32503680001},
        {"id": ""},
        {"data": "invalid"},
        {"data": {"object": {"id": "obj", "object": 42}}},
    ],
)
def test_receipt_normalization_rejects_invalid_envelope(overrides: dict[str, object]) -> None:
    from billing.stripe_event_service import normalize_stripe_event_receipt

    event: dict[str, object] = {
        "id": "evt_strict",
        "type": "unknown.event",
        "created": 1784980800,
        "livemode": False,
        "data": {"object": {"id": "obj", "object": "test.object"}},
    }
    event.update(overrides)

    with pytest.raises(ValueError):
        normalize_stripe_event_receipt(event, stripe_mode="test")


def test_redis_enqueue_failure_after_persist_returns_success_and_db_poll_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, engine = _build_db()
    event_id = "evt_redis_enqueue_failure"

    class _VerifiedEvent:
        def get(self, key: str, default=None):
            return self.to_dict().get(key, default)

        def to_dict(self) -> dict:
            return {
                "id": event_id,
                "type": "unknown.event",
                "created": 1784980800,
                "livemode": False,
                "data": {
                    "object": {
                        "id": "obj_unknown",
                        "object": "test.object",
                        "email": "persisted-customer@example.com",
                        "url": "https://private.example/persisted",
                        "metadata": {"unexpected": "persisted-secret"},
                    }
                },
            }

    class _Request:
        headers = {"Stripe-Signature": "verified-signature"}

        async def stream(self):
            yield b"verified-body"

    class _FailingRedis:
        async def set(self, *_args, **_kwargs) -> None:
            raise ConnectionError("redis unavailable")

    @asynccontextmanager
    async def _redis_context():
        yield _FailingRedis()

    try:
        monkeypatch.setattr(api_router, "SessionLocal", factory)
        monkeypatch.setattr(
            api_router,
            "load_billing_config",
            lambda db: SimpleNamespace(
                mode_configs={
                    "test": SimpleNamespace(webhook_secret="whsec_test"),
                    "live": SimpleNamespace(webhook_secret=None),
                }
            ),
        )
        monkeypatch.setattr(
            api_router.stripe.Webhook,
            "construct_event",
            lambda *_args: _VerifiedEvent(),
        )
        monkeypatch.setattr(api_router, "get_async_redis", _redis_context)

        response = asyncio.run(api_router.stripe_webhook(_Request()))
        assert response == {"received": True}
        persisted = _load_event(factory, event_id)
        assert persisted.processing_status == "pending"
        persisted_json = json.dumps(persisted.payload, sort_keys=True)
        assert persisted.payload["data"]["object"] == {
            "id": "obj_unknown",
            "object": "test.object",
        }
        assert "persisted-customer@example.com" not in persisted_json
        assert "private.example" not in persisted_json
        assert "persisted-secret" not in persisted_json

        monkeypatch.setattr(billing_webhook_worker, "SessionLocal", factory)

        async def _process_as_success(pending_event_id: str, **_kwargs) -> None:
            from billing.stripe_event_service import claim_event, complete_event

            with factory() as db:
                claim = claim_event(db, pending_event_id)
            assert claim is not None
            with factory() as db:
                assert complete_event(db, pending_event_id, claim.claim_token) is True

        monkeypatch.setattr(billing_webhook_worker, "process_event", _process_as_success)
        asyncio.run(billing_webhook_worker.process_due_events(batch_size=10))
        assert _load_event(factory, event_id).processing_status == "processed"
    finally:
        Base.metadata.drop_all(bind=engine)


def test_duplicate_receipt_wakes_retryable_or_stale_but_not_terminal_or_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, engine = _build_db()
    now = datetime.now(timezone.utc)
    try:
        with factory() as db:
            db.add_all(
                [
                    _event("evt_pending"),
                    _event("evt_failed", status="failed", next_attempt_at=now + timedelta(hours=1)),
                    _event(
                        "evt_due_failed",
                        status="failed",
                        next_attempt_at=now - timedelta(seconds=1),
                    ),
                    _event("evt_stale", status="processing", claimed_at=now - timedelta(minutes=6)),
                    _event("evt_active", status="processing", claimed_at=now),
                    _event("evt_done", status="processed"),
                    _event("evt_dead_duplicate", status="dead_letter"),
                ]
            )
            db.commit()
        monkeypatch.setattr(api_router, "SessionLocal", factory)

        assert (
            api_router._persist_stripe_webhook_event(
                "evt_pending", "test.event", now, {"data": {"object": {}}}
            )
            is True
        )
        assert (
            api_router._persist_stripe_webhook_event(
                "evt_failed", "test.event", now, {"data": {"object": {}}}
            )
            is False
        )
        assert (
            api_router._persist_stripe_webhook_event(
                "evt_due_failed", "test.event", now, {"data": {"object": {}}}
            )
            is True
        )
        assert (
            api_router._persist_stripe_webhook_event(
                "evt_stale", "test.event", now, {"data": {"object": {}}}
            )
            is False
        )
        assert (
            api_router._persist_stripe_webhook_event(
                "evt_active", "test.event", now, {"data": {"object": {}}}
            )
            is False
        )
        assert (
            api_router._persist_stripe_webhook_event(
                "evt_done", "test.event", now, {"data": {"object": {}}}
            )
            is False
        )
        assert (
            api_router._persist_stripe_webhook_event(
                "evt_dead_duplicate", "test.event", now, {"data": {"object": {}}}
            )
            is False
        )
    finally:
        Base.metadata.drop_all(bind=engine)


_PLAN_CHANGE_EFFECTIVE_AT = datetime(2027, 2, 1, 12, 0, tzinfo=timezone.utc)


def _scheduled_plan_change_event(
    event_id: str,
    *,
    user_id: int,
    event_created_at: datetime,
    status: str,
    current_period_end: int,
    current_period_start: int | None = None,
    price_id: str = "price_standard_month",
    billing_interval: str = "month",
    items: list[tuple[str, str]] | None = None,
    cancel_at_period_end: bool = False,
    schedule_id: str | None = "sub_sched_scheduled_change",
    subscription_id: str = "sub_scheduled_change",
    customer_id: str = "cus_scheduled_change",
    livemode: bool = False,
    event_type: str = "customer.subscription.updated",
) -> models.StripeEventLog:
    subscription_items = items if items is not None else [(price_id, billing_interval)]
    return _event(
        event_id,
        event_type=event_type,
        event_created_at=event_created_at,
        payload={
            "livemode": livemode,
            "data": {
                "object": {
                    "id": subscription_id,
                    "object": "subscription",
                    "customer": customer_id,
                    "status": status,
                    "current_period_start": (
                        current_period_start
                        if current_period_start is not None
                        else int(_PLAN_CHANGE_EFFECTIVE_AT.timestamp())
                    ),
                    "current_period_end": current_period_end,
                    "cancel_at_period_end": cancel_at_period_end,
                    "schedule": schedule_id,
                    "metadata": {"user_id": str(user_id)},
                    "items": {
                        "data": [
                            {
                                "id": f"si_scheduled_change_{index}",
                                "quantity": 1,
                                "price": {
                                    "id": item_price_id,
                                    "recurring": {"interval": item_interval},
                                },
                            }
                            for index, (item_price_id, item_interval) in enumerate(
                                subscription_items
                            )
                        ]
                    },
                }
            },
        },
    )


def _plan_changed_outbox(**kwargs) -> models.EmailOutbox:
    return models.EmailOutbox(
        user_id=kwargs["user_id"],
        to_email=kwargs["to_email"],
        subject="Plan changed",
        text_body="Plan changed",
        category="billing",
        template_key=kwargs["template_key"],
        correlation_id=kwargs["correlation_id"],
        status="pending",
    )


def test_scheduled_plan_webhook_locks_user_then_subscription_and_activates_only_at_exact_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from billing import Plan
    from billing.plan_change_service import reconcile_pending_plan_change as real_reconcile

    factory, engine = _build_db()
    reconciliation_calls: list[dict[str, object]] = []
    statements_before_reconciliation: list[object] = []
    try:
        with factory() as db:
            user = models.User(
                email="scheduled-plan-change@example.com",
                hashed_password="x",
                role="user",
                credits=5,
            )
            db.add(user)
            db.flush()
            user_id = user.id
            db.add(
                models.Subscription(
                    user_id=user_id,
                    stripe_customer_id="cus_scheduled_change",
                    stripe_subscription_id="sub_scheduled_change",
                    stripe_mode="test",
                    plan_type="plan_specialist",
                    status="past_due",
                    billing_interval="year",
                    current_period_end=datetime(2027, 1, 15, tzinfo=timezone.utc),
                    cancel_at_period_end=True,
                    stripe_schedule_id="sub_sched_scheduled_change",
                    pending_plan_type="plan_standard",
                    pending_billing_interval="month",
                    pending_change_effective_at=_PLAN_CHANGE_EFFECTIVE_AT,
                )
            )
            db.commit()

        monkeypatch.setattr(billing_webhook_worker, "_build_email_outbox", _plan_changed_outbox)
        config = SimpleNamespace(
            app_base_url="https://app.example.com",
            commitment_tier_for_price_id=lambda _price_id: None,
            resolve_plan_price=lambda mode, price, interval: (
                Plan.STANDARD
                if (mode, price, interval) == ("test", "price_standard_month", "month")
                else None
            ),
        )

        def reconciliation_spy(subscription, **kwargs):
            reconciliation_calls.append(dict(kwargs))
            statements_before_reconciliation.extend(captured_statements)
            return real_reconcile(subscription, **kwargs)

        monkeypatch.setattr(
            billing_webhook_worker,
            "reconcile_pending_plan_change",
            reconciliation_spy,
        )

        early_created = _PLAN_CHANGE_EFFECTIVE_AT + timedelta(hours=2)
        early_period_start = int((_PLAN_CHANGE_EFFECTIVE_AT - timedelta(seconds=1)).timestamp())
        early_period_end = int((_PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=31)).timestamp())
        with factory() as db:
            captured_statements: list[object] = []
            execute = db.execute

            def capture_statement(statement, *args, **kwargs):
                captured_statements.append(statement)
                return execute(statement, *args, **kwargs)

            monkeypatch.setattr(db, "execute", capture_statement)
            early_event = _scheduled_plan_change_event(
                "evt_scheduled_change_early",
                user_id=user_id,
                event_created_at=early_created,
                status="active",
                current_period_start=early_period_start,
                current_period_end=early_period_end,
            )
            db.add(early_event)
            db.commit()
            db.expire_all()
            stored_early_event = db.execute(
                select(models.StripeEventLog).where(
                    models.StripeEventLog.event_id == early_event.event_id
                )
            ).scalar_one()
            assert stored_early_event.event_created_at.tzinfo is None
            asyncio.run(
                billing_webhook_worker.handle_event(
                    db,
                    stored_early_event,
                    config=config,
                    stripe_mode="test",
                )
            )
            db.commit()

        with factory() as db:
            subscription = db.execute(
                select(models.Subscription).where(models.Subscription.user_id == user_id)
            ).scalar_one()
            assert subscription.status == "quarantined"
            assert subscription.current_period_end == datetime.fromtimestamp(
                early_period_end, tz=timezone.utc
            ).replace(tzinfo=None)
            assert subscription.cancel_at_period_end is False
            assert subscription.plan_type == "plan_specialist"
            assert subscription.billing_interval == "year"
            assert subscription.stripe_schedule_id == "sub_sched_scheduled_change"
            assert subscription.pending_plan_type == "plan_standard"
            assert subscription.pending_billing_interval == "month"
            assert subscription.pending_change_effective_at is not None
            assert db.execute(select(func.count(models.EmailOutbox.id))).scalar_one() == 0

        assert len(reconciliation_calls) == 1
        source_timestamp = reconciliation_calls[0]["source_event_created_at"]
        assert isinstance(source_timestamp, datetime)
        assert source_timestamp.tzinfo is not None
        assert source_timestamp.utcoffset() is not None
        current_period_start = reconciliation_calls[0]["current_period_start"]
        assert isinstance(current_period_start, datetime)
        assert current_period_start.tzinfo is not None
        assert current_period_start.utcoffset() is not None
        assert current_period_start == datetime.fromtimestamp(early_period_start, tz=timezone.utc)
        locked_statements = [
            statement
            for statement in statements_before_reconciliation
            if getattr(statement, "_for_update_arg", None) is not None
            and getattr(statement, "column_descriptions", None)
        ]
        locked_entities = [
            statement.column_descriptions[0].get("entity") for statement in locked_statements
        ]
        assert locked_entities[-2:] == [models.User, models.Subscription]
        for statement in locked_statements[-2:]:
            assert statement.get_execution_options()["populate_existing"] is True

        due_period_end = int((_PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=30)).timestamp())
        with factory() as db:
            captured_statements = []
            due_event = _scheduled_plan_change_event(
                "evt_scheduled_change_due",
                user_id=user_id,
                event_created_at=_PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=2),
                status="active",
                current_period_start=int(_PLAN_CHANGE_EFFECTIVE_AT.timestamp()),
                current_period_end=due_period_end,
            )
            db.add(due_event)
            db.commit()
            db.expire_all()
            stored_due_event = db.execute(
                select(models.StripeEventLog).where(
                    models.StripeEventLog.event_id == due_event.event_id
                )
            ).scalar_one()
            asyncio.run(
                billing_webhook_worker.handle_event(
                    db,
                    stored_due_event,
                    config=config,
                    stripe_mode="test",
                )
            )
            db.commit()

        assert len(reconciliation_calls) == 2
        assert reconciliation_calls[1]["source_event_created_at"] == (
            _PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=2)
        )
        assert reconciliation_calls[1]["current_period_start"] == (_PLAN_CHANGE_EFFECTIVE_AT)

        with factory() as db:
            subscription = db.execute(
                select(models.Subscription).where(models.Subscription.user_id == user_id)
            ).scalar_one()
            assert subscription.plan_type == "plan_standard"
            assert subscription.billing_interval == "month"
            assert subscription.current_period_end == datetime.fromtimestamp(
                due_period_end, tz=timezone.utc
            ).replace(tzinfo=None)
            assert subscription.stripe_schedule_id is None
            assert subscription.pending_plan_type is None
            assert subscription.pending_billing_interval is None
            assert subscription.pending_change_effective_at is None
            assert subscription.managed_plan_change_schedule_id == ("sub_sched_scheduled_change")
            email = db.execute(select(models.EmailOutbox)).scalar_one()
            assert email.template_key == "plan.changed"
            assert email.correlation_id == "evt_scheduled_change_due"
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _plan_state_config() -> SimpleNamespace:
    from billing import Plan

    prices = {
        ("test", "price_standard_month", "month"): Plan.STANDARD,
        ("test", "price_specialist_year", "year"): Plan.SPECIALIST,
        ("test", "price_starter_year", "year"): Plan.STARTER,
        ("live", "price_live_specialist_year", "year"): Plan.SPECIALIST,
    }
    return SimpleNamespace(
        app_base_url="https://app.example.com",
        commitment_tier_for_price_id=lambda _price_id: None,
        resolve_plan_price=lambda mode, price, interval: prices.get((mode, price, interval)),
    )


def _seed_plan_state_subscription(
    factory: sessionmaker[Session],
    *,
    plan_type: str = "plan_specialist",
    billing_interval: str = "year",
    pending: bool = False,
    pending_plan_type: str = "plan_standard",
    pending_billing_interval: str = "month",
    plan_state_event_created_at: datetime | None = None,
    status: str = "active",
    current_period_end: datetime | None = None,
    cancel_at_period_end: bool = False,
    managed_plan_change_schedule_id: str | None = None,
    stripe_mode: str | None = "test",
) -> int:
    subscription_values: dict[str, object] = {
        "stripe_customer_id": "cus_scheduled_change",
        "stripe_subscription_id": "sub_scheduled_change",
        "stripe_mode": stripe_mode,
        "plan_type": plan_type,
        "status": status,
        "billing_interval": billing_interval,
        "current_period_end": current_period_end or (_PLAN_CHANGE_EFFECTIVE_AT - timedelta(days=1)),
        "cancel_at_period_end": cancel_at_period_end,
    }
    if managed_plan_change_schedule_id is not None:
        subscription_values["managed_plan_change_schedule_id"] = managed_plan_change_schedule_id
    if pending:
        subscription_values.update(
            {
                "stripe_schedule_id": "sub_sched_scheduled_change",
                "pending_plan_type": pending_plan_type,
                "pending_billing_interval": pending_billing_interval,
                "pending_change_effective_at": _PLAN_CHANGE_EFFECTIVE_AT,
            }
        )
    if plan_state_event_created_at is not None:
        subscription_values["plan_state_event_created_at"] = plan_state_event_created_at

    with factory() as db:
        user = models.User(
            email="plan-state-fence@example.com",
            hashed_password="x",
            role="user",
            credits=5,
        )
        db.add(user)
        db.flush()
        user_id = user.id
        db.add(models.Subscription(user_id=user_id, **subscription_values))
        db.commit()
    return user_id


def _handle_persisted_plan_state_event(
    factory: sessionmaker[Session],
    event: models.StripeEventLog,
    *,
    stripe_mode: str = "test",
) -> None:
    event_id = event.event_id
    with factory() as db:
        db.add(event)
        db.commit()
        db.expire_all()
        stored_event = db.execute(
            select(models.StripeEventLog).where(models.StripeEventLog.event_id == event_id)
        ).scalar_one()
        asyncio.run(
            billing_webhook_worker.handle_event(
                db,
                stored_event,
                config=_plan_state_config(),
                stripe_mode=stripe_mode,
            )
        )
        db.commit()


_INVOICE_IMMUTABLE_SUBSCRIPTION_FIELDS = (
    "plan_type",
    "billing_interval",
    "status",
    "current_period_end",
    "cancel_at_period_end",
    "pending_plan_type",
    "pending_billing_interval",
    "pending_change_effective_at",
    "stripe_schedule_id",
    "managed_plan_change_schedule_id",
    "stripe_customer_id",
    "stripe_subscription_id",
    "stripe_mode",
    "plan_state_event_created_at",
)


def _invoice_immutable_subscription_state(
    factory: sessionmaker[Session],
    *,
    user_id: int,
) -> dict[str, object]:
    with factory() as db:
        subscription = db.execute(
            select(models.Subscription).where(models.Subscription.user_id == user_id)
        ).scalar_one()
        return {
            field: getattr(subscription, field) for field in _INVOICE_IMMUTABLE_SUBSCRIPTION_FIELDS
        }


def _base_plan_invoice_event(
    event_id: str,
    *,
    invoice_id: str,
    user_id: int,
    event_created_at: datetime,
    lines: list[tuple[str, str]],
    event_type: str = "invoice.paid",
    customer_id: str = "cus_scheduled_change",
    subscription_id: str = "sub_scheduled_change",
    period_start: int | None = None,
    period_end: int | None = None,
) -> models.StripeEventLog:
    paid = event_type == "invoice.paid"
    effective_period_start = period_start or int(
        (_PLAN_CHANGE_EFFECTIVE_AT - timedelta(days=30)).timestamp()
    )
    effective_period_end = period_end or int(_PLAN_CHANGE_EFFECTIVE_AT.timestamp())
    return _event(
        event_id,
        event_type=event_type,
        event_created_at=event_created_at,
        payload={
            "data": {
                "object": {
                    "id": invoice_id,
                    "object": "invoice",
                    "customer": customer_id,
                    "subscription": subscription_id,
                    "status": "paid" if paid else "open",
                    "paid": paid,
                    "billing_reason": "subscription_cycle",
                    "amount_due": 9900,
                    "amount_paid": 9900 if paid else 0,
                    "currency": "usd",
                    "created": int(event_created_at.timestamp()),
                    "period_start": effective_period_start,
                    "period_end": effective_period_end,
                    "metadata": {"user_id": str(user_id)},
                    "lines": {
                        "data": [
                            {
                                "price": {
                                    "id": price_id,
                                    "recurring": {"interval": interval},
                                }
                            }
                            for price_id, interval in lines
                        ]
                    },
                }
            }
        },
    )


def _assert_invoice_payment(
    db: Session,
    *,
    invoice_id: str,
    status: str,
    customer_id: str = "cus_scheduled_change",
    subscription_id: str = "sub_scheduled_change",
) -> None:
    payment = db.execute(
        select(models.BillingPayment).where(models.BillingPayment.stripe_invoice_id == invoice_id)
    ).scalar_one()
    assert payment.status == status
    assert payment.stripe_customer_id == customer_id
    assert payment.stripe_subscription_id == subscription_id


def test_stale_old_paid_invoice_after_immediate_fence_only_updates_ledger_and_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, engine = _build_db()
    fence = _PLAN_CHANGE_EFFECTIVE_AT
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            plan_type="plan_specialist",
            billing_interval="year",
            plan_state_event_created_at=fence,
            status="trialing",
            current_period_end=fence + timedelta(days=365),
            cancel_at_period_end=True,
        )
        before = _invoice_immutable_subscription_state(factory, user_id=user_id)
        monkeypatch.setattr(
            billing_webhook_worker,
            "_enqueue_email",
            lambda *_args, **_kwargs: None,
        )

        _handle_persisted_plan_state_event(
            factory,
            _base_plan_invoice_event(
                "evt_stale_old_invoice_after_immediate_fence",
                invoice_id="in_stale_old_invoice_after_immediate_fence",
                user_id=user_id,
                event_created_at=fence - timedelta(seconds=1),
                lines=[("price_standard_month", "month")],
                period_end=int((fence - timedelta(days=1)).timestamp()),
            ),
        )

        assert _invoice_immutable_subscription_state(factory, user_id=user_id) == before
        with factory() as db:
            _assert_invoice_payment(
                db,
                invoice_id="in_stale_old_invoice_after_immediate_fence",
                status="paid",
            )
            grant = db.execute(select(models.PlanCreditGrant)).scalar_one()
            assert grant.plan_type == "plan_standard"
            assert grant.interval == "month"
            assert db.execute(select(func.count(models.UserCreditAdjustment.id))).scalar_one() == 1
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_target_price_invoice_before_schedule_qualified_event_grants_once_without_activating_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, engine = _build_db()
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            plan_type="plan_specialist",
            billing_interval="year",
            pending=True,
            pending_plan_type="plan_standard",
            pending_billing_interval="month",
            plan_state_event_created_at=_PLAN_CHANGE_EFFECTIVE_AT - timedelta(days=1),
            status="past_due",
            current_period_end=_PLAN_CHANGE_EFFECTIVE_AT,
            cancel_at_period_end=True,
            managed_plan_change_schedule_id="sub_sched_managed_target_invoice",
        )
        before = _invoice_immutable_subscription_state(factory, user_id=user_id)
        monkeypatch.setattr(
            billing_webhook_worker,
            "_enqueue_email",
            lambda *_args, **_kwargs: None,
        )
        first = _base_plan_invoice_event(
            "evt_target_invoice_before_schedule_event_1",
            invoice_id="in_target_invoice_before_schedule_event",
            user_id=user_id,
            event_created_at=_PLAN_CHANGE_EFFECTIVE_AT,
            lines=[("price_standard_month", "month")],
            period_end=int((_PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=30)).timestamp()),
        )
        duplicate = _base_plan_invoice_event(
            "evt_target_invoice_before_schedule_event_2",
            invoice_id="in_target_invoice_before_schedule_event",
            user_id=user_id,
            event_created_at=_PLAN_CHANGE_EFFECTIVE_AT + timedelta(seconds=1),
            lines=[("price_standard_month", "month")],
            period_end=int((_PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=30)).timestamp()),
        )

        _handle_persisted_plan_state_event(factory, first)
        _handle_persisted_plan_state_event(factory, duplicate)

        assert _invoice_immutable_subscription_state(factory, user_id=user_id) == before
        with factory() as db:
            _assert_invoice_payment(
                db,
                invoice_id="in_target_invoice_before_schedule_event",
                status="paid",
            )
            grant = db.execute(select(models.PlanCreditGrant)).scalar_one()
            assert grant.plan_type == "plan_standard"
            assert grant.interval == "month"
            assert db.execute(select(func.count(models.PlanCreditGrant.id))).scalar_one() == 1
            assert db.execute(select(func.count(models.UserCreditAdjustment.id))).scalar_one() == 1
            assert db.execute(select(func.count(models.BillingPayment.id))).scalar_one() == 1
            assert db.execute(select(models.User.credits)).scalar_one() == 5 + grant.credits
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_unknown_invoice_price_with_valid_interval_cannot_rebind_subscription_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, engine = _build_db()
    invoice_customer_id = "cus_unknown_invoice_identity"
    invoice_subscription_id = "sub_unknown_invoice_identity"
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            pending=True,
            plan_state_event_created_at=_PLAN_CHANGE_EFFECTIVE_AT,
            status="active",
            cancel_at_period_end=True,
            managed_plan_change_schedule_id="sub_sched_managed_unknown_invoice",
            stripe_mode=None,
        )
        before = _invoice_immutable_subscription_state(factory, user_id=user_id)
        monkeypatch.setattr(
            billing_webhook_worker,
            "_enqueue_email",
            lambda *_args, **_kwargs: None,
        )

        _handle_persisted_plan_state_event(
            factory,
            _base_plan_invoice_event(
                "evt_unknown_price_valid_interval",
                invoice_id="in_unknown_price_valid_interval",
                user_id=user_id,
                event_created_at=_PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=1),
                lines=[("price_unknown_year", "year")],
                customer_id=invoice_customer_id,
                subscription_id=invoice_subscription_id,
            ),
        )

        assert _invoice_immutable_subscription_state(factory, user_id=user_id) == before
        with factory() as db:
            _assert_invoice_payment(
                db,
                invoice_id="in_unknown_price_valid_interval",
                status="paid",
                customer_id=invoice_customer_id,
                subscription_id=invoice_subscription_id,
            )
            assert db.execute(select(func.count(models.PlanCreditGrant.id))).scalar_one() == 0
            assert db.execute(select(func.count(models.UserCreditAdjustment.id))).scalar_one() == 0
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_ambiguous_proration_invoice_with_old_and_new_prices_cannot_mutate_plan_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, engine = _build_db()
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            plan_type="plan_standard",
            billing_interval="month",
            pending=True,
            pending_plan_type="plan_specialist",
            pending_billing_interval="year",
            plan_state_event_created_at=_PLAN_CHANGE_EFFECTIVE_AT,
            status="past_due",
            cancel_at_period_end=True,
            managed_plan_change_schedule_id="sub_sched_managed_proration",
        )
        before = _invoice_immutable_subscription_state(factory, user_id=user_id)
        monkeypatch.setattr(
            billing_webhook_worker,
            "_enqueue_email",
            lambda *_args, **_kwargs: None,
        )

        _handle_persisted_plan_state_event(
            factory,
            _base_plan_invoice_event(
                "evt_ambiguous_proration_old_and_new",
                invoice_id="in_ambiguous_proration_old_and_new",
                user_id=user_id,
                event_created_at=_PLAN_CHANGE_EFFECTIVE_AT + timedelta(hours=1),
                lines=[
                    ("price_standard_month", "month"),
                    ("price_specialist_year", "year"),
                ],
                period_end=int((_PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=365)).timestamp()),
            ),
        )

        assert _invoice_immutable_subscription_state(factory, user_id=user_id) == before
        with factory() as db:
            _assert_invoice_payment(
                db,
                invoice_id="in_ambiguous_proration_old_and_new",
                status="paid",
            )
            assert db.execute(select(func.count(models.PlanCreditGrant.id))).scalar_one() == 0
            assert db.execute(select(func.count(models.UserCreditAdjustment.id))).scalar_one() == 0
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_delayed_paid_invoice_after_cancellation_cannot_reactivate_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, engine = _build_db()
    canceled_at = _PLAN_CHANGE_EFFECTIVE_AT
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            plan_type="plan_standard",
            billing_interval="month",
            plan_state_event_created_at=canceled_at,
            status="canceled",
            current_period_end=canceled_at - timedelta(days=1),
            cancel_at_period_end=True,
            managed_plan_change_schedule_id="sub_sched_managed_canceled",
        )
        before = _invoice_immutable_subscription_state(factory, user_id=user_id)
        monkeypatch.setattr(
            billing_webhook_worker,
            "_enqueue_email",
            lambda *_args, **_kwargs: None,
        )

        _handle_persisted_plan_state_event(
            factory,
            _base_plan_invoice_event(
                "evt_delayed_paid_invoice_after_canceled",
                invoice_id="in_delayed_paid_invoice_after_canceled",
                user_id=user_id,
                event_created_at=canceled_at - timedelta(seconds=1),
                lines=[("price_standard_month", "month")],
                period_end=int((canceled_at + timedelta(days=30)).timestamp()),
            ),
        )

        assert _invoice_immutable_subscription_state(factory, user_id=user_id) == before
        with factory() as db:
            _assert_invoice_payment(
                db,
                invoice_id="in_delayed_paid_invoice_after_canceled",
                status="paid",
            )
            grant = db.execute(select(models.PlanCreditGrant)).scalar_one()
            assert grant.plan_type == "plan_standard"
            assert db.execute(select(func.count(models.UserCreditAdjustment.id))).scalar_one() == 1
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_failed_invoice_cannot_overwrite_newer_subscription_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, engine = _build_db()
    newer_state_at = _PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=2)
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            plan_type="plan_standard",
            billing_interval="month",
            pending=True,
            pending_plan_type="plan_specialist",
            pending_billing_interval="year",
            plan_state_event_created_at=newer_state_at,
            status="trialing",
            current_period_end=newer_state_at + timedelta(days=30),
            cancel_at_period_end=False,
            managed_plan_change_schedule_id="sub_sched_managed_failed_invoice",
        )
        before = _invoice_immutable_subscription_state(factory, user_id=user_id)
        monkeypatch.setattr(
            billing_webhook_worker,
            "_enqueue_email",
            lambda *_args, **_kwargs: None,
        )

        _handle_persisted_plan_state_event(
            factory,
            _base_plan_invoice_event(
                "evt_failed_invoice_older_than_subscription_state",
                invoice_id="in_failed_invoice_older_than_subscription_state",
                user_id=user_id,
                event_created_at=newer_state_at - timedelta(seconds=1),
                event_type="invoice.payment_failed",
                lines=[("price_specialist_year", "year")],
                period_end=int((newer_state_at + timedelta(days=365)).timestamp()),
            ),
        )

        assert _invoice_immutable_subscription_state(factory, user_id=user_id) == before
        with factory() as db:
            _assert_invoice_payment(
                db,
                invoice_id="in_failed_invoice_older_than_subscription_state",
                status="failed",
            )
            assert db.execute(select(func.count(models.PlanCreditGrant.id))).scalar_one() == 0
            assert db.execute(select(func.count(models.UserCreditAdjustment.id))).scalar_one() == 0
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_immediate_change_final_fence_blocks_release_event_created_during_stripe_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from billing import Plan
    from billing import router as billing_router

    factory, engine = _build_db()
    request_started_at = datetime(2027, 3, 1, 12, 0, tzinfo=timezone.utc)
    release_event_created_at = request_started_at + timedelta(seconds=1)
    final_fence_at = request_started_at + timedelta(seconds=2)
    target_period_end = int((final_fence_at + timedelta(days=365)).timestamp())
    stale_period_end = int((release_event_created_at + timedelta(days=30)).timestamp())
    clock_values = iter([request_started_at, final_fence_at])

    class _FenceClock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = next(clock_values)
            return value if tz is None else value.astimezone(tz)

    config = SimpleNamespace(
        app_base_url="https://app.example.com",
        stripe_mode="test",
        mode_configs={"test": SimpleNamespace(secret_key="test-explicit-key")},
        price_id_for_mode=lambda mode, plan, interval: {
            ("test", Plan.STANDARD, "month"): "price_standard_month",
            ("test", Plan.SPECIALIST, "year"): "price_specialist_year",
        }.get((mode, plan, interval), ""),
        commitment_tier_for_price_id=lambda _price_id: None,
        resolve_plan_price=lambda mode, price, interval: {
            ("test", "price_standard_month", "month"): Plan.STANDARD,
            ("test", "price_specialist_year", "year"): Plan.SPECIALIST,
        }.get((mode, price, interval)),
    )
    try:
        with factory() as db:
            user = models.User(
                email="immediate-final-fence@example.com",
                hashed_password="x",
                role="user",
                credits=5,
            )
            db.add(user)
            db.flush()
            subscription = models.Subscription(
                user_id=user.id,
                stripe_customer_id="cus_scheduled_change",
                stripe_subscription_id="sub_scheduled_change",
                stripe_mode="test",
                plan_type=Plan.STANDARD.value,
                status="active",
                billing_interval="month",
                current_period_end=request_started_at + timedelta(days=30),
                cancel_at_period_end=False,
                managed_plan_change_schedule_id="sub_sched_release_fence",
            )
            db.add(subscription)
            db.commit()
            user_id = user.id
            subscription_record_id = subscription.id

        schedule_metadata = {
            "qiko_schedule_kind": "plan_change",
            "qiko_subscription_record_id": str(subscription_record_id),
        }
        active_schedule = {
            "id": "sub_sched_release_fence",
            "status": "active",
            "subscription": "sub_scheduled_change",
            "customer": "cus_scheduled_change",
            "metadata": schedule_metadata,
        }
        released_schedule = {
            "id": "sub_sched_release_fence",
            "status": "released",
            "released_subscription": "sub_scheduled_change",
            "customer": "cus_scheduled_change",
            "metadata": schedule_metadata,
        }
        current_subscription = {
            "id": "sub_scheduled_change",
            "customer": "cus_scheduled_change",
            "status": "active",
            "collection_method": "charge_automatically",
            "current_period_start": int(request_started_at.timestamp()),
            "current_period_end": int((request_started_at + timedelta(days=30)).timestamp()),
            "items": {
                "data": [
                    {
                        "id": "si_immediate_fence",
                        "price": {
                            "id": "price_standard_month",
                            "recurring": {"interval": "month"},
                        },
                        "quantity": 1,
                    }
                ]
            },
            "metadata": {},
            "schedule": None,
        }
        attached_subscription = {
            **current_subscription,
            "schedule": "sub_sched_release_fence",
        }
        target_metadata = {
            "user_id": str(user_id),
            "plan": Plan.SPECIALIST.value,
            "billing_interval": "year",
            "change_direction": "upgrade",
            "previous_plan": Plan.STANDARD.value,
            "previous_billing_interval": "month",
        }
        updated_subscription = {
            **current_subscription,
            "status": "trialing",
            "current_period_end": target_period_end,
            "items": {
                "data": [
                    {
                        "id": "si_immediate_fence",
                        "price": {
                            "id": "price_specialist_year",
                            "recurring": {"interval": "year"},
                        },
                        "quantity": 1,
                    }
                ]
            },
            "metadata": target_metadata,
        }
        stripe_side_effects: list[str] = []

        def retrieve_subscription(*_args, **_kwargs):
            if not stripe_side_effects:
                stripe_side_effects.append("subscription_retrieve_attached")
                return attached_subscription
            assert stripe_side_effects == [
                "subscription_retrieve_attached",
                "schedule_retrieve",
                "schedule_release",
            ]
            stripe_side_effects.append("subscription_refresh_detached")
            return current_subscription

        def retrieve_schedule(*_args, **_kwargs):
            stripe_side_effects.append("schedule_retrieve")
            return active_schedule

        def release_schedule(*_args, **_kwargs):
            stripe_side_effects.append("schedule_release")
            return released_schedule

        def modify_subscription(*_args, **_kwargs):
            stripe_side_effects.append("subscription_modify")
            return updated_subscription

        monkeypatch.setattr(billing_router, "datetime", _FenceClock)
        monkeypatch.setattr(
            billing_router,
            "get_billing_config",
            lambda _request, _db=None: config,
        )
        monkeypatch.setattr(
            billing_router,
            "require_not_portal_only",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            billing_router.stripe.SubscriptionSchedule,
            "retrieve",
            retrieve_schedule,
        )
        monkeypatch.setattr(
            billing_router.stripe.SubscriptionSchedule,
            "release",
            release_schedule,
        )
        monkeypatch.setattr(
            billing_router.stripe.Subscription,
            "retrieve",
            retrieve_subscription,
        )
        monkeypatch.setattr(
            billing_router.stripe.Subscription,
            "modify",
            modify_subscription,
        )

        with factory() as db:
            user = db.execute(select(models.User).where(models.User.id == user_id)).scalar_one()
            result = billing_router.execute_plan_change(
                http_request=None,
                request=billing_router.UpgradeRequest(
                    target_plan=Plan.SPECIALIST,
                    billing_interval="year",
                ),
                user=user,
                db=db,
            )

        assert result["immediate"] is True
        assert stripe_side_effects == [
            "subscription_retrieve_attached",
            "schedule_retrieve",
            "schedule_release",
            "subscription_refresh_detached",
            "subscription_modify",
        ]
        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert subscription.plan_state_event_created_at is not None
            operation_fence = subscription.plan_state_event_created_at.replace(tzinfo=timezone.utc)
            assert operation_fence == final_fence_at
            assert request_started_at < release_event_created_at < operation_fence
            state_after_commit = {
                field: getattr(subscription, field)
                for field in (
                    "stripe_customer_id",
                    "stripe_subscription_id",
                    "stripe_mode",
                    "plan_type",
                    "status",
                    "billing_interval",
                    "current_period_end",
                    "cancel_at_period_end",
                    "stripe_schedule_id",
                    "managed_plan_change_schedule_id",
                    "pending_plan_type",
                    "pending_billing_interval",
                    "pending_change_effective_at",
                    "plan_state_event_created_at",
                )
            }
            assert state_after_commit["plan_type"] == Plan.SPECIALIST.value
            assert state_after_commit["billing_interval"] == "year"
            assert state_after_commit["status"] == "trialing"
            assert state_after_commit["managed_plan_change_schedule_id"] is None

        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                "evt_release_between_request_and_final_fence",
                user_id=user_id,
                event_created_at=release_event_created_at,
                status="past_due",
                current_period_start=int(request_started_at.timestamp()),
                current_period_end=stale_period_end,
                price_id="price_standard_month",
                billing_interval="month",
                cancel_at_period_end=True,
                schedule_id="sub_sched_release_fence",
            ),
        )

        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert {
                field: getattr(subscription, field) for field in state_after_commit
            } == state_after_commit
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_due_target_event_sets_full_fence_and_stale_event_cannot_mutate_any_subscription_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, engine = _build_db()
    due_period_end = int((_PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=30)).timestamp())
    stale_period_end = int((_PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=29)).timestamp())
    try:
        user_id = _seed_plan_state_subscription(factory, pending=True)
        monkeypatch.setattr(billing_webhook_worker, "_build_email_outbox", _plan_changed_outbox)

        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                "evt_due_target_fence",
                user_id=user_id,
                event_created_at=_PLAN_CHANGE_EFFECTIVE_AT,
                status="active",
                current_period_end=due_period_end,
            ),
        )

        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert subscription.plan_type == "plan_standard"
            assert subscription.billing_interval == "month"
            assert subscription.stripe_schedule_id is None
            assert subscription.pending_plan_type is None
            assert subscription.pending_billing_interval is None
            assert subscription.pending_change_effective_at is None
            assert subscription.managed_plan_change_schedule_id == ("sub_sched_scheduled_change")
            assert subscription.plan_state_event_created_at is not None
            assert (
                subscription.plan_state_event_created_at.replace(tzinfo=timezone.utc)
                == _PLAN_CHANGE_EFFECTIVE_AT
            )
            email = db.execute(select(models.EmailOutbox)).scalar_one()
            assert email.template_key == "plan.changed"
            assert email.correlation_id == "evt_due_target_fence"

        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                "evt_stale_current_plan_after_due",
                user_id=user_id,
                event_created_at=_PLAN_CHANGE_EFFECTIVE_AT - timedelta(seconds=1),
                status="past_due",
                current_period_end=stale_period_end,
                price_id="price_specialist_year",
                billing_interval="year",
                cancel_at_period_end=True,
                schedule_id=None,
            ),
        )

        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert subscription.status == "active"
            assert subscription.current_period_end == datetime.fromtimestamp(
                due_period_end, tz=timezone.utc
            ).replace(tzinfo=None)
            assert subscription.cancel_at_period_end is False
            assert subscription.plan_type == "plan_standard"
            assert subscription.billing_interval == "month"
            assert subscription.stripe_customer_id == "cus_scheduled_change"
            assert subscription.stripe_subscription_id == "sub_scheduled_change"
            assert subscription.stripe_mode == "test"
            assert subscription.managed_plan_change_schedule_id == ("sub_sched_scheduled_change")
            assert subscription.plan_state_event_created_at is not None
            assert (
                subscription.plan_state_event_created_at.replace(tzinfo=timezone.utc)
                == _PLAN_CHANGE_EFFECTIVE_AT
            )
            assert db.execute(select(func.count(models.EmailOutbox.id))).scalar_one() == 1
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_same_timestamp_conflicting_plan_pair_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, engine = _build_db()
    due_period_end = int((_PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=30)).timestamp())
    conflict_period_end = int((_PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=31)).timestamp())
    try:
        user_id = _seed_plan_state_subscription(factory, pending=True)
        monkeypatch.setattr(
            billing_webhook_worker,
            "_build_email_outbox",
            _plan_changed_outbox,
        )
        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                "evt_same_timestamp_target",
                user_id=user_id,
                event_created_at=_PLAN_CHANGE_EFFECTIVE_AT,
                status="active",
                current_period_end=due_period_end,
            ),
        )

        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                "evt_same_timestamp_conflicting_pair",
                user_id=user_id,
                event_created_at=_PLAN_CHANGE_EFFECTIVE_AT,
                status="past_due",
                current_period_end=conflict_period_end,
                price_id="price_specialist_year",
                billing_interval="year",
                cancel_at_period_end=True,
                schedule_id=None,
            ),
        )

        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert subscription.status == "active"
            assert subscription.current_period_end == datetime.fromtimestamp(
                due_period_end, tz=timezone.utc
            ).replace(tzinfo=None)
            assert subscription.cancel_at_period_end is False
            assert subscription.plan_type == "plan_standard"
            assert subscription.billing_interval == "month"
            assert subscription.stripe_customer_id == "cus_scheduled_change"
            assert subscription.stripe_subscription_id == "sub_scheduled_change"
            assert subscription.stripe_mode == "test"
            assert subscription.managed_plan_change_schedule_id == ("sub_sched_scheduled_change")
            assert subscription.plan_state_event_created_at is not None
            assert (
                subscription.plan_state_event_created_at.replace(tzinfo=timezone.utc)
                == _PLAN_CHANGE_EFFECTIVE_AT
            )
            assert db.execute(select(func.count(models.EmailOutbox.id))).scalar_one() == 1
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.parametrize(
    "event_created_at",
    [
        _PLAN_CHANGE_EFFECTIVE_AT - timedelta(seconds=1),
        _PLAN_CHANGE_EFFECTIVE_AT,
    ],
    ids=["older", "equal"],
)
def test_older_or_equal_different_webhook_is_fully_ignored_by_operation_fence(
    event_created_at: datetime,
) -> None:
    factory, engine = _build_db()
    operation_at = _PLAN_CHANGE_EFFECTIVE_AT
    delayed_period_end = int((operation_at + timedelta(days=365)).timestamp())
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            plan_type="plan_standard",
            billing_interval="month",
            plan_state_event_created_at=operation_at,
        )

        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                f"evt_delayed_after_immediate_{int(event_created_at.timestamp())}",
                user_id=user_id,
                event_created_at=event_created_at,
                status="past_due",
                current_period_end=delayed_period_end,
                price_id="price_specialist_year",
                billing_interval="year",
                cancel_at_period_end=True,
                schedule_id=None,
            ),
        )

        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert subscription.status == "active"
            assert subscription.current_period_end == (
                _PLAN_CHANGE_EFFECTIVE_AT - timedelta(days=1)
            ).replace(tzinfo=None)
            assert subscription.cancel_at_period_end is False
            assert subscription.plan_type == "plan_standard"
            assert subscription.billing_interval == "month"
            assert subscription.stripe_customer_id == "cus_scheduled_change"
            assert subscription.stripe_subscription_id == "sub_scheduled_change"
            assert subscription.stripe_mode == "test"
            assert subscription.plan_state_event_created_at is not None
            assert (
                subscription.plan_state_event_created_at.replace(tzinfo=timezone.utc)
                == operation_at
            )
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_same_second_exact_identity_deletion_overrides_microsecond_operation_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config.plans import resolve_entitled_subscription_plan

    factory, engine = _build_db()
    operation_fence = _PLAN_CHANGE_EFFECTIVE_AT + timedelta(microseconds=750000)
    deletion_created_at = operation_fence.replace(microsecond=0)
    original_period_end = operation_fence + timedelta(days=365)
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            plan_type="plan_specialist",
            billing_interval="year",
            plan_state_event_created_at=operation_fence,
            status="active",
            current_period_end=original_period_end,
            cancel_at_period_end=False,
        )
        monkeypatch.setattr(
            billing_webhook_worker,
            "_enqueue_email",
            lambda *_args, **_kwargs: None,
        )

        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                "evt_same_second_exact_identity_deleted",
                user_id=user_id,
                event_created_at=deletion_created_at,
                event_type="customer.subscription.deleted",
                status="canceled",
                current_period_end=int((operation_fence - timedelta(days=1)).timestamp()),
                price_id="price_standard_month",
                billing_interval="month",
                cancel_at_period_end=True,
                schedule_id=None,
            ),
        )

        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert deletion_created_at.replace(microsecond=0) == operation_fence.replace(
                microsecond=0
            )
            assert deletion_created_at < operation_fence
            assert subscription.status == "canceled"
            assert resolve_entitled_subscription_plan(subscription) is None
            assert subscription.plan_type == "plan_specialist"
            assert subscription.billing_interval == "year"
            assert subscription.current_period_end == original_period_end.replace(tzinfo=None)
            assert subscription.cancel_at_period_end is False
            assert subscription.stripe_customer_id == "cus_scheduled_change"
            assert subscription.stripe_subscription_id == "sub_scheduled_change"
            assert subscription.stripe_mode == "test"
            assert subscription.plan_state_event_created_at is not None
            assert (
                subscription.plan_state_event_created_at.replace(tzinfo=timezone.utc)
                == operation_fence
            )
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_newer_unknown_price_deletion_advances_fence_and_blocks_older_active_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config.plans import resolve_entitled_subscription_plan

    factory, engine = _build_db()
    previous_fence = _PLAN_CHANGE_EFFECTIVE_AT
    deletion_created_at = previous_fence + timedelta(seconds=2)
    stale_active_created_at = previous_fence + timedelta(seconds=1)
    original_period_end = previous_fence + timedelta(days=365)
    deleted_period_end = deletion_created_at + timedelta(days=10)
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            plan_type="plan_specialist",
            billing_interval="year",
            plan_state_event_created_at=previous_fence,
            status="active",
            current_period_end=original_period_end,
            cancel_at_period_end=False,
        )
        monkeypatch.setattr(
            billing_webhook_worker,
            "_enqueue_email",
            lambda *_args, **_kwargs: None,
        )

        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                "evt_newer_unknown_price_deleted",
                user_id=user_id,
                event_created_at=deletion_created_at,
                event_type="customer.subscription.deleted",
                status="canceled",
                current_period_end=int(deleted_period_end.timestamp()),
                price_id="price_unknown_year",
                billing_interval="year",
                cancel_at_period_end=True,
                schedule_id=None,
            ),
        )

        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert subscription.status == "canceled"
            assert resolve_entitled_subscription_plan(subscription) is None
            assert subscription.plan_type == "plan_specialist"
            assert subscription.billing_interval == "year"
            assert subscription.plan_state_event_created_at is not None
            assert (
                subscription.plan_state_event_created_at.replace(tzinfo=timezone.utc)
                == deletion_created_at
            )
        state_after_deletion = _invoice_immutable_subscription_state(
            factory,
            user_id=user_id,
        )

        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                "evt_older_recognized_active_after_deleted",
                user_id=user_id,
                event_created_at=stale_active_created_at,
                status="active",
                current_period_end=int((deletion_created_at + timedelta(days=30)).timestamp()),
                price_id="price_standard_month",
                billing_interval="month",
                cancel_at_period_end=False,
                schedule_id=None,
            ),
        )

        assert (
            _invoice_immutable_subscription_state(
                factory,
                user_id=user_id,
            )
            == state_after_deletion
        )
        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert subscription.status == "canceled"
            assert resolve_entitled_subscription_plan(subscription) is None
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_later_recognized_plan_pair_updates_entitlement_and_advances_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, engine = _build_db()
    later_created_at = _PLAN_CHANGE_EFFECTIVE_AT + timedelta(seconds=1)
    later_period_end = int((_PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=365)).timestamp())
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            plan_type="plan_standard",
            billing_interval="month",
            plan_state_event_created_at=_PLAN_CHANGE_EFFECTIVE_AT,
        )
        monkeypatch.setattr(billing_webhook_worker, "_build_email_outbox", _plan_changed_outbox)

        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                "evt_later_recognized_pair",
                user_id=user_id,
                event_created_at=later_created_at,
                status="active",
                current_period_end=later_period_end,
                price_id="price_starter_year",
                billing_interval="year",
                schedule_id=None,
            ),
        )

        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert subscription.plan_type == "plan_starter"
            assert subscription.billing_interval == "year"
            assert subscription.plan_state_event_created_at is not None
            assert (
                subscription.plan_state_event_created_at.replace(tzinfo=timezone.utc)
                == later_created_at
            )
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.parametrize(
    "price_id",
    ["price_unknown_year", "price_live_specialist_year"],
    ids=["unknown_price", "mode_mismatched_price"],
)
def test_newer_active_unrecognized_price_quarantines_without_changing_historical_plan_pair_or_email(
    monkeypatch: pytest.MonkeyPatch,
    price_id: str,
) -> None:
    from app.config.plans import resolve_entitled_subscription_plan

    factory, engine = _build_db()
    previous_fence = _PLAN_CHANGE_EFFECTIVE_AT
    newer_created_at = previous_fence + timedelta(seconds=1)
    updated_period_end = int((_PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=40)).timestamp())
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            plan_type="plan_standard",
            billing_interval="month",
            plan_state_event_created_at=previous_fence,
        )
        monkeypatch.setattr(
            billing_webhook_worker,
            "_build_email_outbox",
            _plan_changed_outbox,
        )

        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                f"evt_newer_unrecognized_{price_id}",
                user_id=user_id,
                event_created_at=newer_created_at,
                status="active",
                current_period_end=updated_period_end,
                price_id=price_id,
                billing_interval="year",
                cancel_at_period_end=True,
                schedule_id=None,
            ),
        )

        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert subscription.status == "quarantined"
            assert subscription.status not in {"active", "trialing"}
            assert resolve_entitled_subscription_plan(subscription) is None
            assert subscription.plan_type == "plan_standard"
            assert subscription.billing_interval == "month"
            assert subscription.current_period_end == datetime.fromtimestamp(
                updated_period_end, tz=timezone.utc
            ).replace(tzinfo=None)
            assert subscription.cancel_at_period_end is True
            assert subscription.plan_state_event_created_at is not None
            assert (
                subscription.plan_state_event_created_at.replace(tzinfo=timezone.utc)
                == newer_created_at
            )
            assert db.execute(select(func.count(models.EmailOutbox.id))).scalar_one() == 0
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.parametrize(
    ("authoritative_status", "persisted_status"),
    [("past_due", "past_due"), ("active", "quarantined")],
    ids=["status", "quarantine"],
)
def test_unresolved_status_only_event_advances_fence_and_blocks_stale_predecessor(
    authoritative_status: str,
    persisted_status: str,
) -> None:
    from app.config.plans import resolve_entitled_subscription_plan

    factory, engine = _build_db()
    previous_fence = _PLAN_CHANGE_EFFECTIVE_AT
    authoritative_created_at = previous_fence + timedelta(seconds=3)
    stale_predecessor_created_at = previous_fence + timedelta(seconds=2)
    original_period_end = previous_fence + timedelta(days=40)
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            plan_type="plan_specialist",
            billing_interval="year",
            plan_state_event_created_at=previous_fence,
            status="active",
            current_period_end=original_period_end,
            cancel_at_period_end=False,
        )

        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                f"evt_unresolved_authoritative_{authoritative_status}",
                user_id=user_id,
                event_created_at=authoritative_created_at,
                status=authoritative_status,
                current_period_end=int(original_period_end.timestamp()),
                price_id="price_unknown_year",
                billing_interval="year",
                cancel_at_period_end=False,
                schedule_id=None,
            ),
        )

        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert subscription.status == persisted_status
            assert resolve_entitled_subscription_plan(subscription) is None
            assert subscription.plan_type == "plan_specialist"
            assert subscription.billing_interval == "year"
            assert subscription.current_period_end == original_period_end.replace(tzinfo=None)
            assert subscription.cancel_at_period_end is False
            assert subscription.plan_state_event_created_at is not None
            assert (
                subscription.plan_state_event_created_at.replace(tzinfo=timezone.utc)
                == authoritative_created_at
            )
        state_after_authoritative_event = _invoice_immutable_subscription_state(
            factory,
            user_id=user_id,
        )

        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                f"evt_stale_predecessor_after_{authoritative_status}",
                user_id=user_id,
                event_created_at=stale_predecessor_created_at,
                status="active",
                current_period_end=int(
                    (authoritative_created_at + timedelta(days=365)).timestamp()
                ),
                price_id="price_standard_month",
                billing_interval="month",
                cancel_at_period_end=True,
                schedule_id=None,
            ),
        )

        assert (
            _invoice_immutable_subscription_state(
                factory,
                user_id=user_id,
            )
            == state_after_authoritative_event
        )
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.parametrize("pending", [False, True], ids=["without_pending", "with_pending"])
def test_older_unknown_active_price_is_fully_ignored_by_fence(pending: bool) -> None:
    factory, engine = _build_db()
    fence = _PLAN_CHANGE_EFFECTIVE_AT
    original_period_end = fence - timedelta(days=1)
    updated_period_end = int((fence + timedelta(days=40)).timestamp())
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            plan_type="plan_standard",
            billing_interval="month",
            pending=pending,
            pending_plan_type="plan_specialist",
            pending_billing_interval="year",
            plan_state_event_created_at=fence,
            status="past_due",
            current_period_end=original_period_end,
            cancel_at_period_end=False,
        )

        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                f"evt_older_unknown_{pending}",
                user_id=user_id,
                event_created_at=fence - timedelta(seconds=1),
                status="active",
                current_period_end=updated_period_end,
                price_id="price_unknown_year",
                billing_interval="year",
                cancel_at_period_end=True,
                schedule_id="sub_sched_scheduled_change" if pending else None,
            ),
        )

        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert subscription.status == "past_due"
            assert subscription.current_period_end == original_period_end.replace(tzinfo=None)
            assert subscription.cancel_at_period_end is False
            assert subscription.plan_type == "plan_standard"
            assert subscription.billing_interval == "month"
            assert subscription.stripe_customer_id == "cus_scheduled_change"
            assert subscription.stripe_subscription_id == "sub_scheduled_change"
            assert subscription.stripe_mode == "test"
            assert subscription.plan_state_event_created_at is not None
            assert subscription.plan_state_event_created_at.replace(tzinfo=timezone.utc) == fence
            if pending:
                assert subscription.stripe_schedule_id == "sub_sched_scheduled_change"
                assert subscription.pending_plan_type == "plan_specialist"
                assert subscription.pending_billing_interval == "year"
                assert subscription.pending_change_effective_at is not None
            else:
                assert subscription.stripe_schedule_id is None
                assert subscription.pending_plan_type is None
                assert subscription.pending_billing_interval is None
                assert subscription.pending_change_effective_at is None
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.parametrize("stripe_mode", ["test", "live"])
@pytest.mark.parametrize(
    "event_type",
    [
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ],
    ids=["created", "updated", "deleted"],
)
def test_exact_subscription_with_unbound_mode_accepts_one_authenticated_binding_and_applies_state_fence(
    monkeypatch: pytest.MonkeyPatch,
    stripe_mode: str,
    event_type: str,
) -> None:
    factory, engine = _build_db()
    previous_fence = _PLAN_CHANGE_EFFECTIVE_AT - timedelta(days=1)
    event_created_at = _PLAN_CHANGE_EFFECTIVE_AT + timedelta(seconds=1)
    target_plan = "plan_standard" if stripe_mode == "test" else "plan_specialist"
    target_interval = "month" if stripe_mode == "test" else "year"
    target_price = "price_standard_month" if stripe_mode == "test" else "price_live_specialist_year"
    historical_plan = "plan_specialist" if stripe_mode == "test" else "plan_standard"
    historical_interval = "year" if stripe_mode == "test" else "month"
    terminal = event_type == "customer.subscription.deleted"
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            plan_type=historical_plan,
            billing_interval=historical_interval,
            pending=True,
            pending_plan_type=target_plan,
            pending_billing_interval=target_interval,
            plan_state_event_created_at=previous_fence,
            status="past_due",
            current_period_end=_PLAN_CHANGE_EFFECTIVE_AT - timedelta(days=2),
            cancel_at_period_end=True,
            stripe_mode=None,
        )
        monkeypatch.setattr(
            billing_webhook_worker,
            "_enqueue_email",
            lambda *_args, **_kwargs: None,
        )

        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                f"evt_bind_null_mode_{event_type.rsplit('.', 1)[-1]}_{stripe_mode}",
                user_id=user_id,
                event_created_at=event_created_at,
                event_type=event_type,
                status="canceled" if terminal else "active",
                current_period_start=int(_PLAN_CHANGE_EFFECTIVE_AT.timestamp()),
                current_period_end=int(
                    (_PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=30)).timestamp()
                ),
                price_id=target_price,
                billing_interval=target_interval,
                cancel_at_period_end=False,
                livemode=stripe_mode == "live",
            ),
            stripe_mode=stripe_mode,
        )

        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert subscription.stripe_customer_id == "cus_scheduled_change"
            assert subscription.stripe_subscription_id == "sub_scheduled_change"
            assert subscription.stripe_mode == stripe_mode
            assert subscription.plan_state_event_created_at is not None
            assert (
                subscription.plan_state_event_created_at.replace(tzinfo=timezone.utc)
                == event_created_at
            )
            if terminal:
                assert subscription.status == "canceled"
                assert subscription.plan_type == historical_plan
                assert subscription.billing_interval == historical_interval
                assert subscription.stripe_schedule_id == "sub_sched_scheduled_change"
                assert subscription.pending_plan_type == target_plan
                assert subscription.pending_billing_interval == target_interval
                assert subscription.pending_change_effective_at is not None
                assert subscription.managed_plan_change_schedule_id is None
                assert subscription.current_period_end == (
                    _PLAN_CHANGE_EFFECTIVE_AT - timedelta(days=2)
                ).replace(tzinfo=None)
                assert subscription.cancel_at_period_end is True
            else:
                assert subscription.status == "active"
                assert subscription.plan_type == target_plan
                assert subscription.billing_interval == target_interval
                assert subscription.current_period_end == (
                    _PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=30)
                ).replace(tzinfo=None)
                assert subscription.cancel_at_period_end is False
                assert subscription.stripe_schedule_id is None
                assert subscription.pending_plan_type is None
                assert subscription.pending_billing_interval is None
                assert subscription.pending_change_effective_at is None
                assert subscription.managed_plan_change_schedule_id == (
                    "sub_sched_scheduled_change"
                )
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.parametrize(
    "event_type",
    [
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ],
    ids=["created", "updated", "deleted"],
)
def test_exact_subscription_with_conflicting_bound_mode_rejects_before_mutation(
    event_type: str,
) -> None:
    factory, engine = _build_db()
    fence = _PLAN_CHANGE_EFFECTIVE_AT
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            pending=True,
            plan_state_event_created_at=fence,
            status="past_due",
            current_period_end=fence - timedelta(days=2),
            cancel_at_period_end=True,
            stripe_mode="test",
        )
        before = _invoice_immutable_subscription_state(factory, user_id=user_id)
        event = _scheduled_plan_change_event(
            f"evt_conflicting_bound_mode_{event_type.rsplit('.', 1)[-1]}",
            user_id=user_id,
            event_created_at=fence + timedelta(seconds=1),
            event_type=event_type,
            status=("canceled" if event_type == "customer.subscription.deleted" else "active"),
            current_period_end=int((fence + timedelta(days=365)).timestamp()),
            price_id="price_live_specialist_year",
            billing_interval="year",
            cancel_at_period_end=False,
            livemode=True,
        )

        with factory() as db:
            db.add(event)
            db.commit()
            db.expire_all()
            stored_event = db.execute(
                select(models.StripeEventLog).where(
                    models.StripeEventLog.event_id == event.event_id
                )
            ).scalar_one()

            with pytest.raises(
                ValueError,
                match="subscription_mode_reassignment_rejected",
            ):
                asyncio.run(
                    billing_webhook_worker.handle_event(
                        db,
                        stored_event,
                        config=_plan_state_config(),
                        stripe_mode="live",
                    )
                )

            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert {
                field: getattr(subscription, field)
                for field in _INVOICE_IMMUTABLE_SUBSCRIPTION_FIELDS
            } == before
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.parametrize("status", ["active", "trialing"])
@pytest.mark.parametrize(
    ("case", "items"),
    [
        (
            "known_then_unknown",
            [("price_standard_month", "month"), ("price_unknown_year", "year")],
        ),
        (
            "unknown_then_known",
            [("price_unknown_year", "year"), ("price_standard_month", "month")],
        ),
        (
            "two_known",
            [("price_standard_month", "month"), ("price_starter_year", "year")],
        ),
        ("no_items", []),
        ("mode_mismatched", [("price_live_specialist_year", "year")]),
    ],
    ids=[
        "known_then_unknown",
        "unknown_then_known",
        "two_known",
        "no_items",
        "mode_mismatched",
    ],
)
def test_ambiguous_base_subscription_items_quarantine_without_activating_pending_change(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    items: list[tuple[str, str]],
    status: str,
) -> None:
    from app.config.plans import resolve_entitled_subscription_plan

    factory, engine = _build_db()
    previous_fence = _PLAN_CHANGE_EFFECTIVE_AT - timedelta(seconds=1)
    event_created_at = _PLAN_CHANGE_EFFECTIVE_AT + timedelta(seconds=1)
    updated_period_end = _PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=30)
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            plan_type="plan_specialist",
            billing_interval="year",
            pending=True,
            pending_plan_type="plan_standard",
            pending_billing_interval="month",
            plan_state_event_created_at=previous_fence,
            status="past_due",
            current_period_end=_PLAN_CHANGE_EFFECTIVE_AT - timedelta(days=1),
            cancel_at_period_end=True,
        )
        monkeypatch.setattr(
            billing_webhook_worker,
            "_build_email_outbox",
            _plan_changed_outbox,
        )

        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                f"evt_ambiguous_base_items_{case}_{status}",
                user_id=user_id,
                event_created_at=event_created_at,
                status=status,
                current_period_start=int(_PLAN_CHANGE_EFFECTIVE_AT.timestamp()),
                current_period_end=int(updated_period_end.timestamp()),
                items=items,
                cancel_at_period_end=False,
            ),
        )

        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert subscription.status == "quarantined"
            assert resolve_entitled_subscription_plan(subscription) is None
            assert subscription.plan_type == "plan_specialist"
            assert subscription.billing_interval == "year"
            assert subscription.current_period_end == updated_period_end.replace(tzinfo=None)
            assert subscription.cancel_at_period_end is False
            assert subscription.stripe_schedule_id == "sub_sched_scheduled_change"
            assert subscription.pending_plan_type == "plan_standard"
            assert subscription.pending_billing_interval == "month"
            assert subscription.pending_change_effective_at == (
                _PLAN_CHANGE_EFFECTIVE_AT.replace(tzinfo=None)
            )
            assert subscription.managed_plan_change_schedule_id is None
            assert subscription.plan_state_event_created_at is not None
            assert (
                subscription.plan_state_event_created_at.replace(tzinfo=timezone.utc)
                == event_created_at
            )
            assert db.execute(select(func.count(models.EmailOutbox.id))).scalar_one() == 0
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.parametrize(
    ("schedule_case", "schedule_id"),
    [("missing", None), ("foreign", "sub_sched_foreign")],
    ids=["schedule_missing", "schedule_foreign"],
)
@pytest.mark.parametrize(
    "event_type",
    ["customer.subscription.created", "customer.subscription.updated"],
    ids=["created", "updated"],
)
def test_nonstale_preboundary_historical_pair_with_untrusted_schedule_quarantines_and_fences_older_active(
    monkeypatch: pytest.MonkeyPatch,
    schedule_case: str,
    schedule_id: str | None,
    event_type: str,
) -> None:
    from app.config.plans import resolve_entitled_subscription_plan

    factory, engine = _build_db()
    scheduling_fence = _PLAN_CHANGE_EFFECTIVE_AT - timedelta(seconds=10)
    stale_active_created_at = scheduling_fence + timedelta(seconds=2)
    quarantine_created_at = scheduling_fence + timedelta(seconds=5)
    historical_period_start = _PLAN_CHANGE_EFFECTIVE_AT - timedelta(days=30)
    updated_period_end = _PLAN_CHANGE_EFFECTIVE_AT
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            plan_type="plan_specialist",
            billing_interval="year",
            pending=True,
            pending_plan_type="plan_standard",
            pending_billing_interval="month",
            plan_state_event_created_at=scheduling_fence,
            status="past_due",
            current_period_end=_PLAN_CHANGE_EFFECTIVE_AT,
            cancel_at_period_end=True,
        )
        monkeypatch.setattr(
            billing_webhook_worker,
            "_build_email_outbox",
            _plan_changed_outbox,
        )

        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                f"evt_preboundary_historical_{schedule_case}_{event_type.rsplit('.', 1)[-1]}",
                user_id=user_id,
                event_created_at=quarantine_created_at,
                event_type=event_type,
                status="active",
                current_period_start=int(historical_period_start.timestamp()),
                current_period_end=int(updated_period_end.timestamp()),
                price_id="price_specialist_year",
                billing_interval="year",
                cancel_at_period_end=False,
                schedule_id=schedule_id,
            ),
        )

        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert quarantine_created_at < _PLAN_CHANGE_EFFECTIVE_AT
            assert subscription.status == "quarantined"
            assert resolve_entitled_subscription_plan(subscription) is None
            assert subscription.plan_type == "plan_specialist"
            assert subscription.billing_interval == "year"
            assert subscription.stripe_schedule_id == "sub_sched_scheduled_change"
            assert subscription.pending_plan_type == "plan_standard"
            assert subscription.pending_billing_interval == "month"
            assert subscription.pending_change_effective_at == (
                _PLAN_CHANGE_EFFECTIVE_AT.replace(tzinfo=None)
            )
            assert subscription.managed_plan_change_schedule_id is None
            assert subscription.current_period_end == updated_period_end.replace(tzinfo=None)
            assert subscription.cancel_at_period_end is False
            assert subscription.plan_state_event_created_at is not None
            assert (
                subscription.plan_state_event_created_at.replace(tzinfo=timezone.utc)
                == quarantine_created_at
            )
            assert db.execute(select(func.count(models.EmailOutbox.id))).scalar_one() == 0
        quarantined_state = _invoice_immutable_subscription_state(
            factory,
            user_id=user_id,
        )

        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                f"evt_older_active_after_preboundary_quarantine_{schedule_case}_{event_type.rsplit('.', 1)[-1]}",
                user_id=user_id,
                event_created_at=stale_active_created_at,
                event_type="customer.subscription.updated",
                status="active",
                current_period_start=int(historical_period_start.timestamp()),
                current_period_end=int(
                    (_PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=365)).timestamp()
                ),
                price_id="price_specialist_year",
                billing_interval="year",
                cancel_at_period_end=False,
                schedule_id="sub_sched_scheduled_change",
            ),
        )

        assert (
            _invoice_immutable_subscription_state(
                factory,
                user_id=user_id,
            )
            == quarantined_state
        )
        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert subscription.status == "quarantined"
            assert resolve_entitled_subscription_plan(subscription) is None
            assert subscription.plan_type == "plan_specialist"
            assert subscription.billing_interval == "year"
            assert subscription.stripe_schedule_id == "sub_sched_scheduled_change"
            assert subscription.pending_plan_type == "plan_standard"
            assert subscription.pending_billing_interval == "month"
            assert subscription.pending_change_effective_at == (
                _PLAN_CHANGE_EFFECTIVE_AT.replace(tzinfo=None)
            )
            assert subscription.plan_state_event_created_at is not None
            assert (
                subscription.plan_state_event_created_at.replace(tzinfo=timezone.utc)
                == quarantine_created_at
            )
            assert db.execute(select(func.count(models.EmailOutbox.id))).scalar_one() == 0
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.parametrize(
    ("schedule_case", "schedule_id"),
    [("missing", None), ("foreign", "sub_sched_foreign")],
    ids=["schedule_missing", "schedule_foreign"],
)
@pytest.mark.parametrize(
    "event_type",
    ["customer.subscription.created", "customer.subscription.updated"],
    ids=["created", "updated"],
)
def test_preboundary_historical_pair_created_before_scheduling_fence_is_fully_stale(
    schedule_case: str,
    schedule_id: str | None,
    event_type: str,
) -> None:
    factory, engine = _build_db()
    scheduling_fence = _PLAN_CHANGE_EFFECTIVE_AT - timedelta(seconds=10)
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            plan_type="plan_specialist",
            billing_interval="year",
            pending=True,
            pending_plan_type="plan_standard",
            pending_billing_interval="month",
            plan_state_event_created_at=scheduling_fence,
            status="past_due",
            current_period_end=_PLAN_CHANGE_EFFECTIVE_AT,
            cancel_at_period_end=True,
        )
        before = _invoice_immutable_subscription_state(factory, user_id=user_id)

        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                f"evt_before_scheduling_fence_{schedule_case}_{event_type.rsplit('.', 1)[-1]}",
                user_id=user_id,
                event_created_at=scheduling_fence - timedelta(seconds=1),
                event_type=event_type,
                status="active",
                current_period_start=int(
                    (_PLAN_CHANGE_EFFECTIVE_AT - timedelta(days=30)).timestamp()
                ),
                current_period_end=int(
                    (_PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=365)).timestamp()
                ),
                price_id="price_specialist_year",
                billing_interval="year",
                cancel_at_period_end=False,
                schedule_id=schedule_id,
            ),
        )

        assert (
            _invoice_immutable_subscription_state(
                factory,
                user_id=user_id,
            )
            == before
        )
        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert subscription.status == "past_due"
            assert subscription.status != "quarantined"
            assert subscription.plan_type == "plan_specialist"
            assert subscription.billing_interval == "year"
            assert subscription.stripe_schedule_id == "sub_sched_scheduled_change"
            assert subscription.pending_plan_type == "plan_standard"
            assert subscription.pending_billing_interval == "month"
            assert subscription.pending_change_effective_at == (
                _PLAN_CHANGE_EFFECTIVE_AT.replace(tzinfo=None)
            )
            assert subscription.plan_state_event_created_at is not None
            assert (
                subscription.plan_state_event_created_at.replace(tzinfo=timezone.utc)
                == scheduling_fence
            )
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.parametrize(
    ("case", "event_overrides"),
    [
        (
            "recognized_unexpected_pair",
            {
                "price_id": "price_starter_year",
                "billing_interval": "year",
            },
        ),
        (
            "mismatched_schedule_identity",
            {"schedule_id": "sub_sched_unrelated"},
        ),
        (
            "incorrect_effective_boundary",
            {
                "current_period_start": int(
                    (_PLAN_CHANGE_EFFECTIVE_AT + timedelta(seconds=1)).timestamp()
                )
            },
        ),
    ],
    ids=[
        "recognized_unexpected_pair",
        "mismatched_schedule_identity",
        "incorrect_effective_boundary",
    ],
)
@pytest.mark.parametrize(
    "event_type",
    ["customer.subscription.created", "customer.subscription.updated"],
    ids=["created", "updated"],
)
@pytest.mark.parametrize("status", ["active", "trialing"])
def test_nonstale_unexpected_subscription_event_quarantines_complete_pending_change_and_fences_older_active_event(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    event_overrides: dict[str, object],
    event_type: str,
    status: str,
) -> None:
    from app.config.plans import resolve_entitled_subscription_plan

    factory, engine = _build_db()
    previous_fence = _PLAN_CHANGE_EFFECTIVE_AT - timedelta(seconds=1)
    stale_active_created_at = _PLAN_CHANGE_EFFECTIVE_AT + timedelta(seconds=1)
    quarantine_created_at = _PLAN_CHANGE_EFFECTIVE_AT + timedelta(seconds=2)
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            plan_type="plan_specialist",
            billing_interval="year",
            pending=True,
            pending_plan_type="plan_standard",
            pending_billing_interval="month",
            plan_state_event_created_at=previous_fence,
            status="active",
            current_period_end=_PLAN_CHANGE_EFFECTIVE_AT,
            cancel_at_period_end=False,
        )
        monkeypatch.setattr(
            billing_webhook_worker,
            "_build_email_outbox",
            _plan_changed_outbox,
        )

        authoritative_event_fields: dict[str, object] = {
            "current_period_start": int(_PLAN_CHANGE_EFFECTIVE_AT.timestamp()),
            "price_id": "price_standard_month",
            "billing_interval": "month",
            "schedule_id": "sub_sched_scheduled_change",
        }
        authoritative_event_fields.update(event_overrides)
        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                f"evt_pending_quarantine_{case}_{event_type.rsplit('.', 1)[-1]}",
                user_id=user_id,
                event_created_at=quarantine_created_at,
                event_type=event_type,
                status=status,
                current_period_end=int(
                    (_PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=30)).timestamp()
                ),
                cancel_at_period_end=False,
                **authoritative_event_fields,
            ),
        )

        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert subscription.status == "quarantined"
            assert resolve_entitled_subscription_plan(subscription) is None
            assert subscription.plan_type == "plan_specialist"
            assert subscription.billing_interval == "year"
            assert subscription.stripe_schedule_id == "sub_sched_scheduled_change"
            assert subscription.pending_plan_type == "plan_standard"
            assert subscription.pending_billing_interval == "month"
            assert subscription.pending_change_effective_at == (
                _PLAN_CHANGE_EFFECTIVE_AT.replace(tzinfo=None)
            )
            assert subscription.managed_plan_change_schedule_id is None
            assert subscription.plan_state_event_created_at is not None
            assert (
                subscription.plan_state_event_created_at.replace(tzinfo=timezone.utc)
                == quarantine_created_at
            )
            assert db.execute(select(func.count(models.EmailOutbox.id))).scalar_one() == 0
        quarantined_state = _invoice_immutable_subscription_state(
            factory,
            user_id=user_id,
        )

        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                f"evt_older_active_after_pending_quarantine_{case}_{event_type.rsplit('.', 1)[-1]}",
                user_id=user_id,
                event_created_at=stale_active_created_at,
                event_type="customer.subscription.updated",
                status="active",
                current_period_start=int(_PLAN_CHANGE_EFFECTIVE_AT.timestamp()),
                current_period_end=int(
                    (_PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=30)).timestamp()
                ),
                price_id="price_standard_month",
                billing_interval="month",
                cancel_at_period_end=False,
                schedule_id="sub_sched_scheduled_change",
            ),
        )

        assert (
            _invoice_immutable_subscription_state(
                factory,
                user_id=user_id,
            )
            == quarantined_state
        )
        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert subscription.status == "quarantined"
            assert resolve_entitled_subscription_plan(subscription) is None
            assert subscription.plan_type == "plan_specialist"
            assert subscription.billing_interval == "year"
            assert subscription.stripe_schedule_id == "sub_sched_scheduled_change"
            assert subscription.pending_plan_type == "plan_standard"
            assert subscription.pending_billing_interval == "month"
            assert subscription.pending_change_effective_at == (
                _PLAN_CHANGE_EFFECTIVE_AT.replace(tzinfo=None)
            )
            assert subscription.plan_state_event_created_at is not None
            assert (
                subscription.plan_state_event_created_at.replace(tzinfo=timezone.utc)
                == quarantine_created_at
            )
            assert db.execute(select(func.count(models.EmailOutbox.id))).scalar_one() == 0
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.parametrize("status", ["active", "trialing"])
def test_single_recognized_base_subscription_item_activates_pending_change(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    factory, engine = _build_db()
    event_created_at = _PLAN_CHANGE_EFFECTIVE_AT + timedelta(seconds=1)
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            plan_type="plan_specialist",
            billing_interval="year",
            pending=True,
            pending_plan_type="plan_standard",
            pending_billing_interval="month",
            plan_state_event_created_at=_PLAN_CHANGE_EFFECTIVE_AT - timedelta(seconds=1),
            status="past_due",
            cancel_at_period_end=True,
        )
        monkeypatch.setattr(
            billing_webhook_worker,
            "_enqueue_email",
            lambda *_args, **_kwargs: None,
        )

        _handle_persisted_plan_state_event(
            factory,
            _scheduled_plan_change_event(
                f"evt_single_base_item_{status}",
                user_id=user_id,
                event_created_at=event_created_at,
                status=status,
                current_period_start=int(_PLAN_CHANGE_EFFECTIVE_AT.timestamp()),
                current_period_end=int(
                    (_PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=30)).timestamp()
                ),
                items=[("price_standard_month", "month")],
                cancel_at_period_end=False,
            ),
        )

        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert subscription.status == status
            assert subscription.plan_type == "plan_standard"
            assert subscription.billing_interval == "month"
            assert subscription.stripe_schedule_id is None
            assert subscription.pending_plan_type is None
            assert subscription.pending_billing_interval is None
            assert subscription.pending_change_effective_at is None
            assert subscription.managed_plan_change_schedule_id == ("sub_sched_scheduled_change")
            assert subscription.plan_state_event_created_at is not None
            assert (
                subscription.plan_state_event_created_at.replace(tzinfo=timezone.utc)
                == event_created_at
            )
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.parametrize("pending", [False, True], ids=["without_pending", "with_pending"])
@pytest.mark.parametrize(
    ("mismatch", "event_overrides", "handler_mode"),
    [
        (
            "customer",
            {"customer_id": "cus_foreign_identity"},
            "test",
        ),
        (
            "subscription",
            {"subscription_id": "sub_foreign_identity"},
            "test",
        ),
        (
            "stripe_mode",
            {
                "livemode": True,
                "price_id": "price_live_specialist_year",
                "billing_interval": "year",
            },
            "live",
        ),
    ],
    ids=["customer", "subscription", "stripe_mode"],
)
def test_immutable_identity_mismatch_fails_before_any_local_mutation(
    pending: bool,
    mismatch: str,
    event_overrides: dict[str, object],
    handler_mode: str,
) -> None:
    factory, engine = _build_db()
    fence = _PLAN_CHANGE_EFFECTIVE_AT
    original_period_end = fence - timedelta(days=3)
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            pending=pending,
            plan_state_event_created_at=fence,
            status="past_due",
            current_period_end=original_period_end,
            cancel_at_period_end=False,
        )
        event = _scheduled_plan_change_event(
            f"evt_identity_mismatch_{mismatch}_{pending}",
            user_id=user_id,
            event_created_at=fence + timedelta(seconds=1),
            status="active",
            current_period_end=int((fence + timedelta(days=30)).timestamp()),
            cancel_at_period_end=True,
            **event_overrides,
        )
        event_id = event.event_id

        with factory() as db:
            db.add(event)
            db.commit()
            db.expire_all()
            stored_event = db.execute(
                select(models.StripeEventLog).where(models.StripeEventLog.event_id == event_id)
            ).scalar_one()
            subscription = db.execute(select(models.Subscription)).scalar_one()
            original_state = (
                subscription.stripe_customer_id,
                subscription.stripe_subscription_id,
                subscription.stripe_mode,
                subscription.plan_type,
                subscription.billing_interval,
                subscription.status,
                subscription.current_period_end,
                subscription.cancel_at_period_end,
                subscription.plan_state_event_created_at,
                subscription.stripe_schedule_id,
                subscription.pending_plan_type,
                subscription.pending_billing_interval,
                subscription.pending_change_effective_at,
            )

            with pytest.raises(ValueError):
                asyncio.run(
                    billing_webhook_worker.handle_event(
                        db,
                        stored_event,
                        config=_plan_state_config(),
                        stripe_mode=handler_mode,
                    )
                )

            assert (
                subscription.stripe_customer_id,
                subscription.stripe_subscription_id,
                subscription.stripe_mode,
                subscription.plan_type,
                subscription.billing_interval,
                subscription.status,
                subscription.current_period_end,
                subscription.cancel_at_period_end,
                subscription.plan_state_event_created_at,
                subscription.stripe_schedule_id,
                subscription.pending_plan_type,
                subscription.pending_billing_interval,
                subscription.pending_change_effective_at,
            ) == original_state
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.parametrize(
    ("mismatch", "event_overrides", "handler_mode", "expected_error"),
    [
        (
            "customer",
            {"customer_id": "cus_foreign_terminal_identity"},
            "test",
            "subscription_customer_reassignment_rejected",
        ),
        (
            "subscription",
            {"subscription_id": "sub_foreign_terminal_identity"},
            "test",
            "subscription_id_reassignment_rejected",
        ),
        (
            "stripe_mode",
            {"livemode": True},
            "live",
            "subscription_mode_reassignment_rejected",
        ),
    ],
    ids=["customer", "subscription", "stripe_mode"],
)
def test_same_second_terminal_override_rejects_identity_mismatch_before_mutation(
    mismatch: str,
    event_overrides: dict[str, object],
    handler_mode: str,
    expected_error: str,
) -> None:
    factory, engine = _build_db()
    operation_fence = _PLAN_CHANGE_EFFECTIVE_AT + timedelta(microseconds=750000)
    deletion_created_at = operation_fence.replace(microsecond=0)
    try:
        user_id = _seed_plan_state_subscription(
            factory,
            plan_type="plan_specialist",
            billing_interval="year",
            plan_state_event_created_at=operation_fence,
            status="active",
            current_period_end=operation_fence + timedelta(days=365),
            cancel_at_period_end=False,
        )
        event = _scheduled_plan_change_event(
            f"evt_same_second_terminal_mismatch_{mismatch}",
            user_id=user_id,
            event_created_at=deletion_created_at,
            event_type="customer.subscription.deleted",
            status="canceled",
            current_period_end=int((operation_fence - timedelta(days=1)).timestamp()),
            price_id="price_unknown_year",
            billing_interval="year",
            cancel_at_period_end=True,
            schedule_id=None,
            **event_overrides,
        )

        with factory() as db:
            db.add(event)
            db.commit()
            db.expire_all()
            stored_event = db.execute(
                select(models.StripeEventLog).where(
                    models.StripeEventLog.event_id == event.event_id
                )
            ).scalar_one()
            subscription = db.execute(select(models.Subscription)).scalar_one()
            original_state = {
                field: getattr(subscription, field)
                for field in _INVOICE_IMMUTABLE_SUBSCRIPTION_FIELDS
            }

            with pytest.raises(ValueError, match=expected_error):
                asyncio.run(
                    billing_webhook_worker.handle_event(
                        db,
                        stored_event,
                        config=_plan_state_config(),
                        stripe_mode=handler_mode,
                    )
                )

            assert {
                field: getattr(subscription, field)
                for field in _INVOICE_IMMUTABLE_SUBSCRIPTION_FIELDS
            } == original_state
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_duplicate_target_event_does_not_enqueue_a_second_plan_changed_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, engine = _build_db()
    period_end = int((_PLAN_CHANGE_EFFECTIVE_AT + timedelta(days=30)).timestamp())
    try:
        user_id = _seed_plan_state_subscription(factory, pending=True)
        monkeypatch.setattr(billing_webhook_worker, "_build_email_outbox", _plan_changed_outbox)
        for event_id in ("evt_target_first", "evt_target_duplicate"):
            _handle_persisted_plan_state_event(
                factory,
                _scheduled_plan_change_event(
                    event_id,
                    user_id=user_id,
                    event_created_at=_PLAN_CHANGE_EFFECTIVE_AT,
                    status="active",
                    current_period_end=period_end,
                ),
            )

        with factory() as db:
            subscription = db.execute(select(models.Subscription)).scalar_one()
            assert subscription.plan_type == "plan_standard"
            assert subscription.billing_interval == "month"
            assert subscription.managed_plan_change_schedule_id == ("sub_sched_scheduled_change")
            assert subscription.plan_state_event_created_at is not None
            assert (
                subscription.plan_state_event_created_at.replace(tzinfo=timezone.utc)
                == _PLAN_CHANGE_EFFECTIVE_AT
            )
            emails = db.execute(select(models.EmailOutbox)).scalars().all()
            assert len(emails) == 1
            assert emails[0].template_key == "plan.changed"
            assert emails[0].correlation_id == "evt_target_first"
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


POSTGRES_STRIPE_EVENT_TEST_URL = os.getenv("TOPUP_POSTGRES_TEST_DATABASE_URL", "")
_PARSED_POSTGRES_STRIPE_EVENT_TEST_URL = (
    urlparse(POSTGRES_STRIPE_EVENT_TEST_URL) if POSTGRES_STRIPE_EVENT_TEST_URL else None
)
_POSTGRES_STRIPE_EVENT_TEST_IS_LOCAL = bool(
    _PARSED_POSTGRES_STRIPE_EVENT_TEST_URL
    and _PARSED_POSTGRES_STRIPE_EVENT_TEST_URL.scheme.startswith("postgresql")
    and _PARSED_POSTGRES_STRIPE_EVENT_TEST_URL.hostname in {"localhost", "127.0.0.1", "::1"}
)


@pytest.mark.skipif(
    not _POSTGRES_STRIPE_EVENT_TEST_IS_LOCAL,
    reason=(
        "Set TOPUP_POSTGRES_TEST_DATABASE_URL to a migrated local PostgreSQL test database "
        "to run Stripe event claim concurrency coverage"
    ),
)
def test_two_postgres_sessions_only_one_claims_active_event() -> None:
    from billing.stripe_event_service import claim_event

    engine = create_engine(POSTGRES_STRIPE_EVENT_TEST_URL)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    event_id = f"evt_claim_concurrency_{uuid4().hex}"
    setup_db = factory()
    try:
        setup_db.add(_event(event_id))
        setup_db.commit()

        def _claim() -> str | None:
            with factory() as db:
                claim = claim_event(db, event_id)
                return claim.claim_token if claim is not None else None

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: _claim(), range(2)))

        assert sum(result is not None for result in results) == 1
        setup_db.expire_all()
        row = setup_db.execute(
            select(models.StripeEventLog).where(models.StripeEventLog.event_id == event_id)
        ).scalar_one()
        assert row.processing_status == "processing"
        assert row.attempt_count == 1
        assert row.claim_token in results
    finally:
        setup_db.rollback()
        setup_db.execute(
            delete(models.StripeEventLog).where(models.StripeEventLog.event_id == event_id)
        )
        setup_db.commit()
        setup_db.close()
        engine.dispose()
