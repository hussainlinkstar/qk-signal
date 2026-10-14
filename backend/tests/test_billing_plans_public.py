"""Tests for ``/api/v1/billing/plans/public``, the public plan catalog contract.

The endpoint is unauthenticated and read cross-origin by the marketing site, so
these tests pin the published field allowlist and prove that nothing
operational (Stripe state, internal capability flags, private plans) can reach
it. A later change that spreads the raw catalog entry back into the response
fails ``test_plans_public_plan_fields_are_exactly_the_allowlist``.
"""

import json
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import main
from app.config.plans import (
    CAPABILITY_MATRIX,
    INTERNAL_CAPABILITY_KEYS,
    can_use_feature,
)
from database import Base
from middleware import maintenance as maintenance_module
from services.public_plan_catalog import (
    PUBLIC_FEATURE_MATRIX_FIELDS,
    PUBLIC_PAYLOAD_FIELDS,
    PUBLIC_PLAN_CATALOG_TTL_SECONDS,
    PUBLIC_PLAN_FIELDS,
    reset_public_plan_catalog_cache,
)


PUBLIC_ENDPOINT = "/api/v1/billing/plans/public"

# Withdrawn from the customer-facing plan comparison on 6 Oct (SIGV2-1167),
# still live entitlement gates (SIGV2-1168).
WITHDRAWN_FEATURES = (
    "can_use_slack_integration",
    "can_use_teams_integration",
    "has_dedicated_strategist",
    "has_done_for_you_execution",
)

# The concept each withdrawn key states in prose, so the sweep catches a copy
# string as well as a flag name. The Teams pattern is deliberately narrow:
# plan_specialist's highlight says "Built for scaling teams and agencies",
# which is the English word, not the Microsoft Teams integration.
WITHDRAWN_CONCEPTS = {
    "can_use_slack_integration": re.compile(r"slack", re.IGNORECASE),
    "can_use_teams_integration": re.compile(
        r"(?:microsoft|ms)\s+teams|teams\s+(?:integration|connection|channel|message)",
        re.IGNORECASE,
    ),
    "has_dedicated_strategist": re.compile(r"strategist", re.IGNORECASE),
    "has_done_for_you_execution": re.compile(r"done[\s-]?for[\s-]?you", re.IGNORECASE),
}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _build_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session_local()
    return db, engine


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def billing_ctx(monkeypatch):
    db, engine = _build_db()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    async def noop_enforce_audit_limit(*_a, **_kw):
        return None

    async def noop_tenant_resolver(request, call_next):
        return await call_next(request)

    monkeypatch.setattr(main, "enforce_authenticated_audit_limit", noop_enforce_audit_limit)
    monkeypatch.setattr(main, "tenant_resolver_middleware", noop_tenant_resolver)
    monkeypatch.setattr(
        maintenance_module,
        "_get_maintenance_state",
        lambda: {"active": False, "message": "", "allowed_ips": []},
    )

    main.app.dependency_overrides[main.get_db] = override_get_db

    reset_public_plan_catalog_cache()
    client = TestClient(main.app)

    yield {
        "client": client,
        "db": db,
        "engine": engine,
        "monkeypatch": monkeypatch,
    }

    main.app.dependency_overrides.clear()
    reset_public_plan_catalog_cache()
    db.close()
    Base.metadata.drop_all(bind=engine)


# ===================================================================
# Happy path: endpoint returns without authentication
# ===================================================================


def test_plans_public_returns_200_without_auth(billing_ctx):
    resp = billing_ctx["client"].get(PUBLIC_ENDPOINT)
    assert resp.status_code == 200


def test_plans_public_returns_plan_list(billing_ctx):
    resp = billing_ctx["client"].get(PUBLIC_ENDPOINT)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["plans"], list)
    assert [plan["id"] for plan in data["plans"]] == [
        "plan_starter",
        "plan_standard",
        "plan_specialist",
        "plan_executive",
    ]


def test_plans_public_omits_credit_price_usd(billing_ctx):
    resp = billing_ctx["client"].get(PUBLIC_ENDPOINT)
    assert resp.status_code == 200
    data = resp.json()
    assert "credit_price_usd" not in data


def test_plans_public_returns_annual_discount_pct(billing_ctx):
    """The site renders the annual saving, so it must not hardcode the rate."""
    data = billing_ctx["client"].get(PUBLIC_ENDPOINT).json()
    assert data["annual_discount_pct"] == 20


def test_plans_public_sets_cache_control(billing_ctx):
    resp = billing_ctx["client"].get(PUBLIC_ENDPOINT)
    assert resp.headers["cache-control"] == f"public, max-age={PUBLIC_PLAN_CATALOG_TTL_SECONDS}"
    assert "origin" in resp.headers["vary"].lower()


# ===================================================================
# Output field allowlist
# ===================================================================


def test_plans_public_payload_fields_are_exactly_the_allowlist(billing_ctx):
    data = billing_ctx["client"].get(PUBLIC_ENDPOINT).json()
    assert tuple(data.keys()) == PUBLIC_PAYLOAD_FIELDS


def test_plans_public_plan_fields_are_exactly_the_allowlist(billing_ctx):
    """Fails loudly if anyone spreads the raw catalog entry back into the payload."""
    data = billing_ctx["client"].get(PUBLIC_ENDPOINT).json()
    for plan in data["plans"]:
        assert tuple(plan.keys()) == PUBLIC_PLAN_FIELDS, f"unexpected fields on {plan.get('id')}"


def test_plans_public_carries_everything_a_pricing_card_needs(billing_ctx):
    data = billing_ctx["client"].get(PUBLIC_ENDPOINT).json()
    plans_by_id = {plan["id"]: plan for plan in data["plans"]}

    executive = plans_by_id["plan_executive"]
    # Negotiated since SIGV2-1211: the approved table reads "Contact Us", so
    # the pricing card gets the two flags it needs to say that and no figure
    # to quote. The list price still exists in CAPABILITY_MATRIX for MRR and
    # Stripe; this payload is where it stops.
    assert executive["monthly_price_usd"] is None
    assert executive["annual_price_usd"] is None
    assert executive["has_custom_pricing"] is True
    assert executive["cta"] == "contact"
    # Credits are the internal cost unit (SIGV2-1102) and customers never see
    # them, so the public payload must not carry a credit quantity. This
    # assertion previously required the opposite, which is why the leak
    # survived: removing the field failed a test.
    assert "credits_per_month" not in executive
    assert executive["max_sites"] == -1
    assert executive["max_audits"] == 2000
    assert executive["name"] == "Executive"
    assert executive["description"]
    assert executive["features"]

    starter = plans_by_id["plan_starter"]
    assert starter["monthly_price_usd"] == 0
    assert starter["annual_price_usd"] is None


# ===================================================================
# Published entitlement matrix (SIGV2-1107)
# ===================================================================


def test_plans_public_publishes_the_entitlement_matrix(billing_ctx):
    """The capability rows WEB-1041 could not state truthfully from the
    ``features`` arrays, published as (key, label, minimum plan)."""
    data = billing_ctx["client"].get(PUBLIC_ENDPOINT).json()
    matrix = data["features_matrix"]
    assert isinstance(matrix, list) and matrix

    by_key = {entry["key"]: entry for entry in matrix}
    assert by_key["has_pdf_audit_reports"]["min_plan_id"] == "plan_starter"
    assert by_key["has_pdf_audit_reports"]["label"] == "PDF audit report generation"
    assert by_key["api_access"]["min_plan_id"] == "plan_specialist"
    assert by_key["has_multi_workspace_federation"]["label"] == "Multiple workspaces"

    for entry in matrix:
        assert tuple(entry.keys()) == PUBLIC_FEATURE_MATRIX_FIELDS
        assert entry["label"].strip(), entry
        assert entry["min_plan_id"] in {plan["id"] for plan in data["plans"]}


def test_plans_public_matrix_states_a_capability_a_features_array_omits(billing_ctx):
    """Executive's ``features`` array does not mention PDF reports (the list is
    truncated at seven highlights) while the gate grants them from Starter.
    Inferring absence from that array is the false negative this field exists
    to prevent (SIGV2-1107, which named Specialist; see the unit test)."""
    data = billing_ctx["client"].get(PUBLIC_ENDPOINT).json()
    plan_ids = [plan["id"] for plan in data["plans"]]
    executive = next(plan for plan in data["plans"] if plan["id"] == "plan_executive")
    assert not any("pdf audit reports" in feature.lower() for feature in executive["features"])

    entry = next(e for e in data["features_matrix"] if e["key"] == "has_pdf_audit_reports")
    for plan_id in ("plan_specialist", "plan_executive"):
        assert plan_ids.index(plan_id) >= plan_ids.index(entry["min_plan_id"])
        assert can_use_feature(plan_id, "has_pdf_audit_reports") is True


def test_plans_public_matrix_publishes_no_credit_or_internal_key(billing_ctx):
    """SIGV2-1149 removed ``credits_per_month`` from this payload; the new
    field must not reintroduce an internal unit under any spelling."""
    data = billing_ctx["client"].get(PUBLIC_ENDPOINT).json()
    keys = {entry["key"] for entry in data["features_matrix"]}
    assert not keys & set(INTERNAL_CAPABILITY_KEYS)
    assert "credit" not in json.dumps(data["features_matrix"]).lower()


def test_plans_public_never_offers_a_withdrawn_feature(billing_ctx):
    """SIGV2-1167 withdrew Slack, Teams, the dedicated strategist and
    done-for-you execution from the customer-facing plan comparison as not
    offered or not yet active.

    One sweep of the whole served payload, not three narrow checks: the
    endpoint must not offer them as an entitlement row, as a plan highlight in
    a ``features`` array, or in a presentation string. Before SIGV2-1107 the
    payload advertised a dedicated strategist in the last two, which would
    have meant promising a prospect what the product had stopped showing a
    paying customer.
    """
    data = billing_ctx["client"].get(PUBLIC_ENDPOINT).json()
    serialized = json.dumps(data)
    for key, concept in WITHDRAWN_CONCEPTS.items():
        assert key not in serialized, f"the payload names {key}"
        found = concept.findall(serialized)
        assert found == [], f"the payload still offers {key}: {found}"
    assert {entry["key"] for entry in data["features_matrix"]}.isdisjoint(WITHDRAWN_FEATURES)


def test_plans_public_withholding_changed_no_entitlement_gate():
    """SIGV2-1168: all four are live gates. The keys stay in the capability
    matrix and keep granting exactly what they granted; only what the public
    endpoint claims has changed."""
    for withdrawn in WITHDRAWN_FEATURES:
        assert withdrawn in CAPABILITY_MATRIX["plan_executive"]
        assert can_use_feature("plan_executive", withdrawn) is True
    assert can_use_feature("plan_specialist", "can_use_slack_integration") is True
    assert can_use_feature("plan_specialist", "has_dedicated_strategist") is False


# ===================================================================
# Leak checks
# ===================================================================


def test_plans_public_never_exposes_internal_capability_flags(billing_ctx):
    """No gating flag reaches the anonymous payload.

    ``has_custom_pricing`` is the one allowed exception (SIGV2-1211). It gates
    nothing: ``plan_validator`` lists it under ``UNGATED_CAPABILITIES``
    precisely because it names a commercial arrangement rather than a code
    path, and a pricing card cannot say "Contact Us" without it. Everything
    else that starts ``has_``/``can_`` stays out, which is what this test is
    really defending.
    """
    data = billing_ctx["client"].get(PUBLIC_ENDPOINT).json()
    for plan in data["plans"]:
        assert "capabilities" not in plan
        for key in plan:
            if key == "has_custom_pricing":
                continue
            assert not key.startswith("has_"), key
            assert not key.startswith("can_"), key
        assert "max_parallel_audits" not in plan
        assert "max_workflows_per_project" not in plan
        assert "pdf_white_label" not in plan
        assert "has_white_label" not in plan
        assert "has_multi_workspace_federation" not in plan


def test_plans_public_never_exposes_stripe_or_operational_state(billing_ctx):
    serialized = json.dumps(billing_ctx["client"].get(PUBLIC_ENDPOINT).json()).lower()
    for forbidden in ("stripe", "price_id", "sk_test", "sk_live", "checkout", "billing_enabled"):
        assert forbidden not in serialized, f"public payload leaks {forbidden}"


def test_plans_public_excludes_private_plans(billing_ctx):
    data = billing_ctx["client"].get(PUBLIC_ENDPOINT).json()
    assert "plan_agency_trial" not in {plan["id"] for plan in data["plans"]}
    assert "agency trial" not in json.dumps(data).lower()


# ===================================================================
# Independence from Stripe / billing configuration
# ===================================================================


def test_plans_public_does_not_read_billing_config(billing_ctx, monkeypatch):
    """The public path must not load Stripe config, so an unauthenticated
    caller cannot trigger a billing-config read (or be affected by one)."""

    def _explode(*_args, **_kwargs):  # pragma: no cover - must never be called
        raise AssertionError("public plan catalog must not load the billing config")

    monkeypatch.setattr("billing.router.load_billing_config", _explode)
    reset_public_plan_catalog_cache()

    resp = billing_ctx["client"].get(PUBLIC_ENDPOINT)
    assert resp.status_code == 200


def test_plans_public_no_stripe_returns_200(billing_ctx, monkeypatch):
    """Without Stripe configured the endpoint still publishes the catalog."""
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY_TEST", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY_LIVE", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)

    resp = billing_ctx["client"].get(PUBLIC_ENDPOINT)
    assert resp.status_code == 200
    assert len(resp.json()["plans"]) == 4


def test_plans_public_with_stripe_configured_returns_same_shape(billing_ctx, monkeypatch):
    """Stripe configuration state is not part of the public contract, so
    configuring it must not add fields to the response."""
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("FEATURE_BILLING_ENABLED", "true")
    monkeypatch.setenv("STRIPE_PRICE_STANDARD_TEST", "price_fake_nc")
    reset_public_plan_catalog_cache()

    data = billing_ctx["client"].get(PUBLIC_ENDPOINT).json()
    for plan in data["plans"]:
        assert tuple(plan.keys()) == PUBLIC_PLAN_FIELDS


# ===================================================================
# Catalog is the single source of truth
# ===================================================================


def test_plans_public_reflects_a_catalog_price_change(billing_ctx, monkeypatch):
    """Editing the plan catalog is the only edit needed to change the price,
    and a warm cache cannot keep serving the old one."""
    billing_ctx["client"].get(PUBLIC_ENDPOINT)  # prime the cache with the real price

    # Specialist rather than Executive since SIGV2-1211: Executive is custom
    # priced and publishes no figure, so it can no longer demonstrate that a
    # catalog edit propagates.
    monkeypatch.setitem(CAPABILITY_MATRIX["plan_specialist"], "monthly_price_usd", 1234)

    data = billing_ctx["client"].get(PUBLIC_ENDPOINT).json()
    specialist = next(plan for plan in data["plans"] if plan["id"] == "plan_specialist")
    assert specialist["monthly_price_usd"] == 1234
    assert specialist["annual_price_usd"] == pytest.approx(11846.4)


# ===================================================================
# Idempotent / repeated calls
# ===================================================================


def test_plans_public_idempotent(billing_ctx):
    """Multiple sequential calls should return identical results."""
    resp1 = billing_ctx["client"].get(PUBLIC_ENDPOINT)
    resp2 = billing_ctx["client"].get(PUBLIC_ENDPOINT)
    assert resp1.status_code == resp2.status_code == 200
    assert resp1.json() == resp2.json()
