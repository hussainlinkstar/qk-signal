from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models  # noqa: E402
from auth.credits import apply_dynamic_ai_credit_charge  # noqa: E402
from database import Base  # noqa: E402
from operational_settings import get_or_create_operational_settings  # noqa: E402
from services.billing_calculator import calculate_dynamic_billing  # noqa: E402


def _build_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return testing_session(), engine


def _cleanup(db, engine):
    db.close()
    Base.metadata.drop_all(bind=engine)


def test_apply_dynamic_charge_records_credit_adjustment_and_ledger() -> None:
    db, engine = _build_db()
    try:
        user = models.User(
            email="ledger-user@example.com",
            hashed_password="x",
            role="user",
            credits=40,
            notifications_enabled=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        workspace = models.Workspace(name="Acme", owner_id=user.id)
        db.add(workspace)
        db.commit()
        db.refresh(workspace)

        project = models.Project(
            name="Ledger Project",
            domain_url="https://example.com",
            workspace_id=workspace.id,
        )
        db.add(project)
        db.commit()
        db.refresh(project)

        billing = calculate_dynamic_billing(
            model_name="gpt-5.4",
            usage={"prompt_tokens": 12000, "completion_tokens": 4000},
            plan_type="plan_specialist",
            feature_key="content_brief.generate",
            tier_class="deep",
            policy_version="v1",
        )
        consumed = apply_dynamic_ai_credit_charge(
            db,
            user=user,
            billing=billing,
            provider="openai",
            reason_code="content_brief.generate",
            feature_key="content_brief.generate",
            tier_class="deep",
            routing_profile="server_policy",
            request_id="req-ledger-1",
            workspace_id=workspace.id,
            project_id=project.id,
        )
        db.commit()
        db.refresh(user)

        assert consumed > 0
        assert user.credits == 40 - consumed
        assert db.query(models.UserCreditAdjustment).count() == 1

        ledger_row = db.query(models.AIEconomicsLedgerEntry).one()
        assert ledger_row.policy_version == "v2"
        assert ledger_row.feature_key == "content_brief.generate"
        assert ledger_row.request_id == "req-ledger-1"
        assert ledger_row.workspace_id == workspace.id
        assert ledger_row.project_id == project.id
        assert ledger_row.credits_charged == consumed
        assert ledger_row.shadow_policy_version is None
        assert ledger_row.schema_version == "2"
        assert ledger_row.token_cost_usd > 0
    finally:
        _cleanup(db, engine)


def test_apply_dynamic_charge_populates_shadow_v2_when_enabled() -> None:
    db, engine = _build_db()
    try:
        user = models.User(
            email="ledger-shadow@example.com",
            hashed_password="x",
            role="user",
            credits=60,
            notifications_enabled=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        settings = get_or_create_operational_settings(db)
        settings.pricing_v2_shadow_mode = True
        settings.credit_engine_v2_enabled = False
        db.commit()

        billing = calculate_dynamic_billing(
            model_name="gpt-5.4",
            usage={"prompt_tokens": 10000, "completion_tokens": 3500},
            plan_type="plan_standard",
            feature_key="aeo_mentions.analyze_batch",
            tier_class="fast",
            policy_version="v1",
        )
        consumed = apply_dynamic_ai_credit_charge(
            db,
            user=user,
            billing=billing,
            provider="openai",
            reason_code="aeo_mentions.analyze_batch",
            feature_key="aeo_mentions.analyze_batch",
            tier_class="fast",
        )
        db.commit()

        ledger_row = db.query(models.AIEconomicsLedgerEntry).one()
        assert consumed > 0
        assert ledger_row.policy_version == "v1"
        assert ledger_row.shadow_policy_version == "v2"
        assert ledger_row.shadow_credits_charged is not None
    finally:
        _cleanup(db, engine)


def test_apply_dynamic_charge_populates_shadow_v3_when_enabled() -> None:
    db, engine = _build_db()
    try:
        user = models.User(
            email="ledger-shadow-v3@example.com",
            hashed_password="x",
            role="user",
            credits=80,
            notifications_enabled=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        settings = get_or_create_operational_settings(db)
        settings.credit_engine_v2_enabled = True
        settings.pricing_v3_shadow_mode = True
        db.commit()

        billing = calculate_dynamic_billing(
            model_name="gpt-5.4",
            usage={"prompt_tokens": 9000, "completion_tokens": 3200},
            plan_type="plan_specialist",
            feature_key="content_brief.generate",
            tier_class="deep",
            policy_version="v2",
        )
        consumed = apply_dynamic_ai_credit_charge(
            db,
            user=user,
            billing=billing,
            provider="openai",
            reason_code="content_brief.generate",
            feature_key="content_brief.generate",
            tier_class="deep",
        )
        db.commit()

        ledger_row = db.query(models.AIEconomicsLedgerEntry).one()
        assert consumed > 0
        assert ledger_row.policy_version == "v2"
        assert ledger_row.shadow_policy_version == "v3"
        assert ledger_row.shadow_credits_charged is not None
    finally:
        _cleanup(db, engine)
