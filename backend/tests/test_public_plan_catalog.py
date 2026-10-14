"""Tests for the public plan catalog projection, its cache, its rate limit and
the route-scoped CORS allowance that lets the marketing site read it.

Security-relevant properties pinned here:

* output allowlist: no capability matrix, no Stripe state, no private plan;
* the published entitlement matrix (SIGV2-1107) states a minimum plan that
  agrees with the backend gate, carries curated customer-facing copy, and
  omits internal, credit-denominated and withdrawn capabilities;
* cache cannot serve a price from another build, and cannot be poisoned into
  publishing an off-contract payload;
* Redis being unavailable degrades to the in-process cache instead of
  rebuilding on every request or failing the request;
* the endpoint is rate limited under its own key prefix;
* an origin that is not configured gets no CORS allowance.
"""

import asyncio
import contextlib
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
    CAPABILITY_DESCRIPTIONS,
    CAPABILITY_MATRIX,
    INTERNAL_CAPABILITY_KEYS,
    MINIMUM_PLAN_BY_FEATURE,
    PRIVATE_PLAN_IDS,
    PUBLIC_PLAN_TYPES,
    UNPUBLISHED_CAPABILITY_KEYS,
    can_use_feature,
    customer_facing_capability_label,
    diff_capabilities,
    get_plan_capabilities,
    get_plan_weight,
)
from core.config import settings
from core.public_site_cors import (
    apply_public_site_cors,
    is_public_site_origin,
    resolve_public_site_origins,
)
from database import Base
from middleware import maintenance as maintenance_module
from routers import api_router as api_router_module
from services import public_plan_catalog as catalog_module
from services.public_plan_catalog import (
    PUBLIC_CAPABILITY_LABEL_OVERRIDES,
    PUBLIC_FEATURE_MATRIX_FIELDS,
    PUBLIC_PAYLOAD_FIELDS,
    PUBLIC_PLAN_FIELDS,
    RATE_LIMIT_KEY_PREFIX,
    WITHHELD_PUBLIC_CAPABILITY_KEYS,
    build_public_features_matrix,
    build_public_plan_catalog,
    catalog_version,
    get_public_plan_catalog,
    reset_public_plan_catalog_cache,
)


PUBLIC_ENDPOINT = "/api/v1/billing/plans/public"
PREPROD_SITE_ORIGIN = "https://www.preprod.qiko.ai"

# Withdrawn from the customer-facing plan comparison on 6 Oct (SIGV2-1167).
# Still live entitlement gates (SIGV2-1168), so they must stay in the
# capability matrix while disappearing from the published payload.
WITHDRAWN_FEATURES = (
    "can_use_slack_integration",
    "can_use_teams_integration",
    "has_dedicated_strategist",
    "has_done_for_you_execution",
)

# The concept each withdrawn key states in prose, so the sweep below catches a
# copy string as well as a flag name. The Teams pattern is deliberately narrow:
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
# Helpers
# ---------------------------------------------------------------------------


class _StubRedis:
    """Minimal async Redis stand-in recording how often it is consulted."""

    def __init__(self, stored: str | None = None, fail: bool = False):
        self.stored = stored
        self.fail = fail
        self.get_calls = 0
        self.set_calls = 0
        self.keys: list[str] = []
        self.ttl = None

    async def get(self, key):
        self.get_calls += 1
        self.keys.append(key)
        if self.fail:
            raise ConnectionError("redis unavailable")
        return self.stored

    async def set(self, key, value, ex=None):
        self.set_calls += 1
        self.keys.append(key)
        if self.fail:
            raise ConnectionError("redis unavailable")
        self.stored = value
        self.ttl = ex


def _patch_redis(monkeypatch, stub: _StubRedis, connect_fails: bool = False):
    calls = {"opened": 0}

    @contextlib.asynccontextmanager
    async def _fake_get_async_redis(**_kwargs):
        calls["opened"] += 1
        if connect_fails:
            raise ConnectionError("redis unavailable")
        yield stub

    monkeypatch.setattr(catalog_module, "get_async_redis", _fake_get_async_redis)
    return calls


def _published_plan_order() -> list[str]:
    """Plan ids in the order the payload publishes them."""
    return [plan["id"] for plan in build_public_plan_catalog()["plans"]]


def _matrix_by_key() -> dict[str, dict]:
    return {entry["key"]: entry for entry in build_public_plan_catalog()["features_matrix"]}


def _resolves_present(entry: dict, plan_id: str) -> bool:
    """Resolve one published row for one plan the way a consumer must.

    The payload publishes a minimum plan id, so a consumer answers "does this
    plan include it" by position in the published plan ladder. This helper is
    that consumer.
    """
    order = _published_plan_order()
    return order.index(plan_id) >= order.index(entry["min_plan_id"])


@pytest.fixture(autouse=True)
def _clean_cache():
    reset_public_plan_catalog_cache()
    yield
    reset_public_plan_catalog_cache()


@pytest.fixture
def public_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = session_local()

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

    yield TestClient(main.app)

    main.app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


# ===================================================================
# Output allowlist
# ===================================================================


def test_public_plan_types_exclude_private_plans():
    assert PUBLIC_PLAN_TYPES == (
        "plan_starter",
        "plan_standard",
        "plan_specialist",
        "plan_executive",
    )
    assert not set(PUBLIC_PLAN_TYPES) & PRIVATE_PLAN_IDS


def test_build_projects_only_allowlisted_plan_fields():
    for plan in build_public_plan_catalog()["plans"]:
        assert tuple(plan.keys()) == PUBLIC_PLAN_FIELDS


def test_build_projects_only_allowlisted_payload_fields():
    assert tuple(build_public_plan_catalog().keys()) == PUBLIC_PAYLOAD_FIELDS


def test_build_drops_every_internal_capability_flag():
    """The capability matrix has flags describing unshipped and internal-only
    behaviour, so none of its keys may appear other than the published
    commercial numbers.

    ``has_custom_pricing`` joined that published set in SIGV2-1211. It is not
    a leak of a gating flag: it carries no entitlement (``plan_validator``
    lists it under ``UNGATED_CAPABILITIES``, nothing reads it at runtime), and
    publishing it is the only way a plan can say "Contact Us" instead of a
    figure. The spelling matches the key because that is what the marketing
    site already recognises.
    """
    published = {"monthly_price_usd", "max_sites", "max_audits", "has_custom_pricing"}
    for plan in build_public_plan_catalog()["plans"]:
        internal_keys = set(get_plan_capabilities(plan["id"])) - published
        assert internal_keys, "expected the capability matrix to have internal flags"
        assert not internal_keys & set(plan)


def test_build_publishes_no_credit_field():
    """Credits are the internal cost unit (SIGV2-1102); serving the quantity on
    the unauthenticated pricing payload was the defect this pins against. No
    published key may carry credit data at all, under any name."""
    for plan in build_public_plan_catalog()["plans"]:
        assert "credits_per_month" not in plan
        credit_keys = [key for key in plan if "credit" in key.lower()]
        assert credit_keys == [], f"{plan['id']} publishes credit fields: {credit_keys}"
    assert not any("credit" in field.lower() for field in PUBLIC_PLAN_FIELDS)


def test_build_carries_the_pricing_card_numbers():
    plans = {plan["id"]: plan for plan in build_public_plan_catalog()["plans"]}
    assert plans["plan_standard"]["monthly_price_usd"] == 49
    assert plans["plan_standard"]["annual_price_usd"] == pytest.approx(470.4)
    assert plans["plan_specialist"]["monthly_price_usd"] == 99
    assert plans["plan_specialist"]["max_sites"] == 10
    assert plans["plan_starter"]["max_audits"] == 1
    assert plans["plan_starter"]["features"]


def test_build_reflects_a_price_edit_in_the_plan_catalog(monkeypatch):
    """A price edit reaches the payload, demonstrated on a listed plan.

    Executive used to be the subject here. It cannot be any more: it is
    custom priced since SIGV2-1211, so the whole point of its projection is
    that no figure reaches the payload however the matrix is edited. That
    property is asserted separately below, and the price-propagation property
    this test exists for moves to Specialist.
    """
    monkeypatch.setitem(CAPABILITY_MATRIX["plan_specialist"], "monthly_price_usd", 1500)
    plans = {plan["id"]: plan for plan in build_public_plan_catalog()["plans"]}
    assert plans["plan_specialist"]["monthly_price_usd"] == 1500


def test_a_custom_priced_plan_publishes_no_figure_whatever_the_matrix_says(monkeypatch):
    """Editing the internal list price cannot make Executive quote one.

    The list price stays in the matrix for MRR and Stripe, so the only thing
    standing between it and an anonymous pricing page is this projection.
    """
    monkeypatch.setitem(CAPABILITY_MATRIX["plan_executive"], "monthly_price_usd", 1500)
    plans = {plan["id"]: plan for plan in build_public_plan_catalog()["plans"]}
    executive = plans["plan_executive"]
    assert executive["monthly_price_usd"] is None
    assert executive["annual_price_usd"] is None
    assert executive["has_custom_pricing"] is True
    assert executive["cta"] == "contact"


# ===================================================================
# Published entitlement matrix (SIGV2-1107)
# ===================================================================


def test_features_matrix_is_published_additively():
    """The field is new; nothing a current consumer already reads moves.

    The marketing site parses this endpoint defensively, so an additive field
    is ignored safely until it reads it, but only if the fields it already
    reads are untouched.
    """
    assert PUBLIC_PLAN_FIELDS == (
        "id",
        "name",
        "description",
        "highlight",
        "color",
        "monthly_price_usd",
        "annual_price_usd",
        # Added by SIGV2-1211, additively and at the end of the price block:
        # every field a consumer already read keeps its name and meaning, so
        # the marketing site keeps working untouched and can adopt these two
        # when it is ready to render "Contact Us".
        "has_custom_pricing",
        "cta",
        "max_sites",
        "max_audits",
        "features",
    )
    assert [field for field in PUBLIC_PAYLOAD_FIELDS if field != "features_matrix"] == [
        "plans",
        "annual_discount_pct",
        "catalog_version",
    ]

    payload = build_public_plan_catalog()
    assert payload["annual_discount_pct"] == 20
    standard = next(plan for plan in payload["plans"] if plan["id"] == "plan_standard")
    assert tuple(standard.keys()) == PUBLIC_PLAN_FIELDS
    assert standard["monthly_price_usd"] == 49
    assert standard["annual_price_usd"] == pytest.approx(470.4)
    assert standard["features"]


def test_features_matrix_entry_fields_are_exactly_the_allowlist():
    assert PUBLIC_FEATURE_MATRIX_FIELDS == ("key", "label", "min_plan_id")
    matrix = build_public_plan_catalog()["features_matrix"]
    assert matrix, "expected published entitlement rows"
    for entry in matrix:
        assert tuple(entry.keys()) == PUBLIC_FEATURE_MATRIX_FIELDS


def test_published_plan_order_is_the_entitlement_ladder():
    """A consumer resolves a minimum plan by position, so the published order
    has to be the price/entitlement ladder rather than dict order."""
    order = _published_plan_order()
    assert order == sorted(order, key=get_plan_weight)
    assert order == ["plan_starter", "plan_standard", "plan_specialist", "plan_executive"]


def test_features_matrix_min_plan_is_always_a_published_plan():
    published = set(PUBLIC_PLAN_TYPES)
    for entry in build_public_features_matrix():
        assert entry["min_plan_id"] in published, entry
        assert entry["min_plan_id"] not in PRIVATE_PLAN_IDS, entry


def test_pdf_reports_resolve_present_despite_the_features_arrays():
    """The named false negative this ticket exists to prevent (SIGV2-1107).

    ``MINIMUM_PLAN_BY_FEATURE`` grants ``has_pdf_audit_reports`` from Starter,
    so every plan has it, but the ``features`` arrays are marketing highlights
    and do not all say so. A renderer inferring absence from them would tell a
    prospective customer the opposite of the truth, which is why the website
    omitted the row instead of guessing.

    One correction to the ticket, which named Specialist: on ``main``
    Specialist's array does list PDF reports (it is the seventh and last item
    it keeps). The array that omits them is **Executive's**, because
    ``build_plan_feature_list`` truncates at seven entries and Executive has
    more highlights than that. So the false negative is live, and it is worse
    than described: a prospect reading the arrays would conclude the $999 plan
    has no PDF reports while the free plan does.
    """
    plans = {plan["id"]: plan for plan in build_public_plan_catalog()["plans"]}
    executive_features = " ".join(plans["plan_executive"]["features"]).lower()
    assert "pdf audit reports" not in executive_features, (
        "Executive's features array now lists PDF reports, so this test no "
        "longer covers the false negative it was written for"
    )
    assert "performance sync" not in executive_features

    assert MINIMUM_PLAN_BY_FEATURE["has_pdf_audit_reports"] == "plan_starter"
    entry = _matrix_by_key()["has_pdf_audit_reports"]
    assert entry["min_plan_id"] == "plan_starter"
    assert entry["label"] == "PDF audit report generation"

    # The entitlement resolves present for every plan, including the two whose
    # own highlight list is silent about it.
    for plan_id in _published_plan_order():
        assert can_use_feature(plan_id, "has_pdf_audit_reports") is True
        assert _resolves_present(entry, plan_id) is True
    assert _resolves_present(entry, "plan_specialist") is True
    assert _resolves_present(entry, "plan_executive") is True


def test_every_published_row_resolves_exactly_like_the_backend_gate():
    """Every (plan, capability) pair the matrix implies must agree with
    ``can_use_feature``, in both directions: no false positive, and no false
    negative, including capabilities a plan's features array never mentions."""
    for entry in build_public_features_matrix():
        for plan_id in _published_plan_order():
            assert _resolves_present(entry, plan_id) == can_use_feature(
                plan_id, entry["key"]
            ), f"{plan_id} / {entry['key']} disagrees with the entitlement gate"


def test_features_matrix_publishes_no_credit_field_under_any_name():
    """Credits are the internal cost unit; SIGV2-1149 removed the quantity
    from this exact payload. The guard is by name, not by key list, so a new
    spelling cannot slip through before anyone updates a constant."""
    for entry in build_public_features_matrix():
        assert "credit" not in entry["key"].lower(), entry
        assert "credit" not in entry["label"].lower(), entry
    assert not any("credit" in field.lower() for field in PUBLIC_FEATURE_MATRIX_FIELDS)
    assert "credit" not in json.dumps(build_public_plan_catalog()).lower()


def test_features_matrix_omits_every_internal_capability_key():
    assert INTERNAL_CAPABILITY_KEYS, "expected at least one internal capability key"
    published = set(_matrix_by_key())
    assert not published & set(INTERNAL_CAPABILITY_KEYS)
    assert "credits_per_month" not in published


def test_features_matrix_omits_a_newly_declared_internal_key(monkeypatch):
    """Adding a key to ``INTERNAL_CAPABILITY_KEYS`` is enough to unpublish it."""
    monkeypatch.setattr(
        catalog_module,
        "INTERNAL_CAPABILITY_KEYS",
        frozenset(set(INTERNAL_CAPABILITY_KEYS) | {"api_access"}),
    )
    assert "api_access" not in {entry["key"] for entry in build_public_features_matrix()}


def test_an_internal_key_declared_as_an_entitlement_is_still_unpublished(monkeypatch):
    """``credits_per_month`` is not in ``MINIMUM_PLAN_BY_FEATURE`` today, so
    without this the internal-key exclusion would be untested. Declaring a
    minimum plan for it must not put the internal cost unit back on the
    pricing page (SIGV2-1149 removed exactly that)."""
    monkeypatch.setitem(MINIMUM_PLAN_BY_FEATURE, "credits_per_month", "plan_starter")
    assert "credits_per_month" not in {entry["key"] for entry in build_public_features_matrix()}
    assert "credit" not in json.dumps(build_public_plan_catalog()).lower()


def test_a_credit_named_capability_is_never_published(monkeypatch):
    """The belt-and-braces guard: a credit quantity under a new spelling is
    refused by name, before anyone remembers to declare it internal, and even
    though it has a perfectly good label."""
    monkeypatch.setitem(MINIMUM_PLAN_BY_FEATURE, "has_credit_rollover", "plan_specialist")
    monkeypatch.setitem(CAPABILITY_DESCRIPTIONS, "has_credit_rollover", "Rollover allowance")
    monkeypatch.setitem(CAPABILITY_MATRIX["plan_specialist"], "has_credit_rollover", True)

    assert "has_credit_rollover" not in {entry["key"] for entry in build_public_features_matrix()}
    assert "credit" not in json.dumps(build_public_plan_catalog()).lower()


def test_the_public_payload_never_offers_a_withdrawn_feature():
    """SIGV2-1167 withdrew these four from the in-app plan comparison as not
    offered or not yet active, so the public payload must not offer them to a
    prospect either: not as an entitlement row, not as a plan highlight, and
    not in a presentation string.

    Deliberately one sweep of the whole serialised payload rather than three
    narrow assertions, so the next place someone states one of these is caught
    wherever it is added.
    """
    assert WITHHELD_PUBLIC_CAPABILITY_KEYS == frozenset(WITHDRAWN_FEATURES)
    serialized = json.dumps(build_public_plan_catalog())
    for key, concept in WITHDRAWN_CONCEPTS.items():
        assert key not in serialized, f"the payload names {key}"
        found = concept.findall(serialized)
        assert found == [], f"the payload still offers {key}: {found}"


def test_withholding_from_the_payload_changes_no_entitlement_gate():
    """SIGV2-1168: the four keys are live gates. They stay in the capability
    matrix and keep granting exactly what they granted; only the published
    payload omits them."""
    for withdrawn in WITHDRAWN_FEATURES:
        assert withdrawn in MINIMUM_PLAN_BY_FEATURE
        assert withdrawn in CAPABILITY_MATRIX["plan_executive"]
        assert can_use_feature("plan_executive", withdrawn) is True


# Served entitlements that are not offerable MVP features (SIGV2-1206). They
# stay live gates like the four above, but nothing customer-facing may state
# them: not the public features matrix, not the upgrade preview diff, not a
# plan highlight.
UNOFFERABLE_MVP_FEATURES = (
    "cms_push",
    "lead_widget",
    "entity_authority",
    "can_use_workflow_automations",
    "max_workflows_per_project",
)


def test_the_public_payload_never_offers_an_unavailable_mvp_feature():
    serialized = json.dumps(build_public_plan_catalog())
    for key in UNOFFERABLE_MVP_FEATURES:
        assert key not in serialized, f"the payload names {key}"
        assert key in UNPUBLISHED_CAPABILITY_KEYS
    # The audit-time entity analysis is a separate key and stays published:
    # the standalone authority offer is the only one withdrawn.
    assert "entity_analysis" in serialized


def test_plan_diffs_never_name_an_unavailable_mvp_feature():
    """diff_capabilities feeds the upgrade preview modal, so an Executive
    upgrade must not arrive promising CMS push or workflow automations."""
    for current, target in (
        ("plan_standard", "plan_executive"),
        ("plan_executive", "plan_standard"),
        ("plan_starter", "plan_specialist"),
    ):
        diff = diff_capabilities(current, target)
        named = {label for label in diff["gained"] + diff["lost"]}
        for key in UNOFFERABLE_MVP_FEATURES:
            label = CAPABILITY_DESCRIPTIONS[key]
            assert label not in named, f"{current} -> {target} offered {key}"


def test_a_new_flag_with_no_curated_label_cannot_publish_itself():
    """customer_facing_capability_label is the publish boundary for the
    upgrade diff: an unknown or unpublished key returns None, not a titled
    flag name."""
    assert customer_facing_capability_label("has_brand_new_flag") is None
    for key in UNOFFERABLE_MVP_FEATURES + WITHDRAWN_FEATURES:
        assert customer_facing_capability_label(key) is None
    # The positive case: a curated label is returned. SIGV2-1210 widened this
    # row's copy to "API & MCP access" when the MCP server shipped, because
    # the same key on the same plans now reaches both halves of the surface.
    assert customer_facing_capability_label("api_access") == "API & MCP access"
    # And the MCP key itself publishes nothing, so the row is not duplicated.
    assert customer_facing_capability_label("mcp_access") is None


def test_every_published_row_has_curated_customer_facing_copy():
    """A label is a copy decision: an internal flag name, or the titled-key
    fallback derived from it, is not customer copy."""
    for entry in build_public_features_matrix():
        assert isinstance(entry["label"], str)
        assert entry["label"].strip(), entry
        # Copy resolves through the public override first (admin wording that
        # names internals, e.g. a vendor), then the curated description map.
        assert entry["label"] == (
            PUBLIC_CAPABILITY_LABEL_OVERRIDES.get(entry["key"])
            or CAPABILITY_DESCRIPTIONS[entry["key"]]
        )
        assert entry["label"] != entry["key"].replace("_", " ").title()


def test_admin_wording_that_names_a_vendor_never_reaches_the_payload():
    """``has_live_engine_tracking``'s CAPABILITY_DESCRIPTIONS entry is written
    for an admin audience and names the provider carrying the measurement. The
    published row states the capability through the public override instead."""
    entry = _matrix_by_key()["has_live_engine_tracking"]
    assert entry["label"] == PUBLIC_CAPABILITY_LABEL_OVERRIDES["has_live_engine_tracking"]
    assert "openrouter" not in entry["label"].lower()
    # The override is load-bearing only while the admin label names the vendor.
    assert "openrouter" in CAPABILITY_DESCRIPTIONS["has_live_engine_tracking"].lower()


def test_a_capability_with_no_customer_label_is_omitted(monkeypatch):
    """A capability outside CAPABILITY_DESCRIPTIONS has no curated copy, so
    the row is dropped rather than falling back to a titled flag name."""
    monkeypatch.delitem(CAPABILITY_DESCRIPTIONS, "api_access")
    assert "api_access" not in {entry["key"] for entry in build_public_features_matrix()}


def test_features_matrix_covers_the_capability_rows_the_comparison_table_needs():
    """WEB-1041's comparison table shipped five of ten rows because the
    capability rows could not be stated truthfully. These are the rows it
    needs, minus the one SIGV2-1167 withdrew."""
    published = _matrix_by_key()
    expected = {
        "api_access": "plan_specialist",
        "has_competitor_analysis": "plan_specialist",
        "has_advanced_reporting": "plan_specialist",
        "can_schedule_audits": "plan_specialist",
        "has_multi_workspace_federation": "plan_executive",
        "has_white_label": "plan_executive",
        "has_pdf_audit_reports": "plan_starter",
        "has_performance_sync": "plan_starter",
    }
    for key, min_plan_id in expected.items():
        assert key in published, f"{key} missing from the published matrix"
        assert published[key]["min_plan_id"] == min_plan_id


def test_features_matrix_omits_a_capability_no_public_plan_has(monkeypatch):
    """Several matrix flags describe unshipped work. A capability the gate
    grants to no public plan has nothing truthful to publish, so it is omitted
    instead of being published against the most expensive plan."""
    monkeypatch.setattr(
        catalog_module,
        "can_use_feature",
        lambda plan, key: False if key == "api_access" else can_use_feature(plan, key),
    )
    assert "api_access" not in {entry["key"] for entry in build_public_features_matrix()}


# ===================================================================
# Caching
# ===================================================================


def test_cache_miss_writes_both_caches(monkeypatch):
    stub = _StubRedis()
    _patch_redis(monkeypatch, stub)

    payload = asyncio.run(get_public_plan_catalog())

    assert payload == build_public_plan_catalog()
    assert stub.set_calls == 1
    assert stub.ttl == catalog_module.PUBLIC_PLAN_CATALOG_TTL_SECONDS


def test_shared_cache_entry_is_served(monkeypatch):
    shared = build_public_plan_catalog()
    shared["annual_discount_pct"] = 77  # marker proving the shared copy was used
    stub = _StubRedis(stored=json.dumps(shared))
    _patch_redis(monkeypatch, stub)

    assert asyncio.run(get_public_plan_catalog())["annual_discount_pct"] == 77


def test_local_cache_absorbs_repeat_requests(monkeypatch):
    stub = _StubRedis()
    calls = _patch_redis(monkeypatch, stub)

    for _ in range(5):
        asyncio.run(get_public_plan_catalog())

    # One read plus one write on the first call, nothing afterwards.
    assert calls["opened"] == 2
    assert stub.get_calls == 1


def test_redis_outage_degrades_to_the_local_cache(monkeypatch):
    """A Redis outage must not turn the pricing page into a request amplifier
    and must not fail the request."""
    stub = _StubRedis(fail=True)
    calls = _patch_redis(monkeypatch, stub, connect_fails=True)

    first = asyncio.run(get_public_plan_catalog())
    for _ in range(4):
        repeat = asyncio.run(get_public_plan_catalog())

    assert first == build_public_plan_catalog()
    assert repeat == first
    # Only the first (cold) request attempted Redis: one read, one write.
    assert calls["opened"] == 2


def test_cache_key_changes_with_the_price(monkeypatch):
    """A build with a different price reads a different key, so it can never
    inherit the previous build's answer."""
    before = catalog_version()
    stub = _StubRedis()
    _patch_redis(monkeypatch, stub)
    asyncio.run(get_public_plan_catalog())
    keys_before = list(stub.keys)

    monkeypatch.setitem(CAPABILITY_MATRIX["plan_executive"], "monthly_price_usd", 1500)
    after = catalog_version()

    assert after != before
    assert all(before in key for key in keys_before)
    assert all(after not in key for key in keys_before)


def test_stale_entry_from_another_build_is_rejected(monkeypatch):
    """A cached payload written before a price change must never be published,
    even if it somehow lands under the current key.

    Specialist is the subject rather than Executive since SIGV2-1211:
    Executive publishes no figure at all now, so a tampered price on it would
    be caught by the projection instead of by the staleness check, which is
    not what this test is for.
    """
    stale = build_public_plan_catalog()
    stale["catalog_version"] = "0123456789abcdef"
    for plan in stale["plans"]:
        if plan["id"] == "plan_specialist":
            plan["monthly_price_usd"] = 111
    stub = _StubRedis(stored=json.dumps(stale))
    _patch_redis(monkeypatch, stub)

    payload = asyncio.run(get_public_plan_catalog())
    specialist = next(plan for plan in payload["plans"] if plan["id"] == "plan_specialist")
    assert specialist["monthly_price_usd"] == 99


@pytest.mark.parametrize(
    "poison",
    [
        "extra_plan_field",
        "extra_payload_field",
        "unexpected_plan_id",
        "extra_plan",
        "not_a_dict",
    ],
)
def test_poisoned_cache_entry_is_rejected(monkeypatch, poison):
    """Redis is shared infrastructure, so a cached value is untrusted input."""
    payload = build_public_plan_catalog()
    if poison == "extra_plan_field":
        payload["plans"][0]["stripe_price_id"] = "price_evil"
    elif poison == "extra_payload_field":
        payload["checkout_available"] = True
    elif poison == "unexpected_plan_id":
        payload["plans"][0]["id"] = "plan_agency_trial"
    elif poison == "extra_plan":
        payload["plans"].append(dict(payload["plans"][0]))
    else:
        payload = ["not", "a", "dict"]

    stub = _StubRedis(stored=json.dumps(payload))
    _patch_redis(monkeypatch, stub)

    assert asyncio.run(get_public_plan_catalog()) == build_public_plan_catalog()


def test_catalog_version_covers_the_published_entitlement_matrix(monkeypatch):
    """The fingerprint goes into the cache key, so a build that moved a
    minimum plan must read a different key instead of inheriting the old
    claim."""
    before = catalog_version()
    monkeypatch.setitem(MINIMUM_PLAN_BY_FEATURE, "api_access", "plan_standard")
    assert catalog_version() != before


def test_catalog_version_covers_a_reworded_capability_label(monkeypatch):
    before = catalog_version()
    monkeypatch.setitem(CAPABILITY_DESCRIPTIONS, "api_access", "API and integration access")
    assert catalog_version() != before


def test_catalog_version_covers_the_published_field_set(monkeypatch):
    """Adding or removing a published field changes the fingerprint, which is
    what makes adding ``features_matrix`` unable to read a cached entry
    written in the previous shape."""
    before = catalog_version()
    monkeypatch.setattr(
        catalog_module,
        "PUBLIC_PAYLOAD_FIELDS",
        tuple(field for field in PUBLIC_PAYLOAD_FIELDS if field != "features_matrix"),
    )
    assert catalog_version() != before


def test_cached_entry_in_the_previous_payload_shape_is_rejected(monkeypatch):
    """A copy written before this field existed cannot be served."""
    stale = build_public_plan_catalog()
    stale.pop("features_matrix")
    stub = _StubRedis(stored=json.dumps(stale))
    _patch_redis(monkeypatch, stub)

    payload = asyncio.run(get_public_plan_catalog())
    assert payload["features_matrix"] == build_public_features_matrix()


@pytest.mark.parametrize(
    "poison",
    [
        "credit_row",
        "internal_row",
        "withdrawn_row",
        "upgraded_claim",
        "extra_entry_field",
        "not_a_list",
    ],
)
def test_poisoned_features_matrix_is_rejected(monkeypatch, poison):
    """An entitlement row is a public claim about what a plan includes, and
    rebuilding it is pure in-process work, so a cached matrix is only accepted
    when it still agrees with this build."""
    payload = build_public_plan_catalog()
    if poison == "credit_row":
        payload["features_matrix"].append(
            {
                "key": "credits_per_month",
                "label": "Credits per month",
                "min_plan_id": "plan_starter",
            }
        )
    elif poison == "internal_row":
        payload["features_matrix"][0] = dict(payload["features_matrix"][0], key="credits_per_month")
    elif poison == "withdrawn_row":
        payload["features_matrix"].append(
            {
                "key": "has_dedicated_strategist",
                "label": "Dedicated strategist support",
                "min_plan_id": "plan_executive",
            }
        )
    elif poison == "upgraded_claim":
        payload["features_matrix"] = [
            dict(entry, min_plan_id="plan_executive") for entry in payload["features_matrix"]
        ]
    elif poison == "extra_entry_field":
        payload["features_matrix"][0]["stripe_price_id"] = "price_evil"
    else:
        payload["features_matrix"] = "not a list"

    stub = _StubRedis(stored=json.dumps(payload))
    _patch_redis(monkeypatch, stub)

    assert asyncio.run(get_public_plan_catalog()) == build_public_plan_catalog()


def test_corrupt_cache_entry_is_ignored(monkeypatch):
    stub = _StubRedis(stored="{not json")
    _patch_redis(monkeypatch, stub)

    assert asyncio.run(get_public_plan_catalog()) == build_public_plan_catalog()


# ===================================================================
# Rate limiting
# ===================================================================


def test_endpoint_rate_limits_under_its_own_key_prefix(public_client, monkeypatch):
    recorded = {}

    async def _record(**kwargs):
        recorded.update(kwargs)

    monkeypatch.setattr(api_router_module, "enforce_rate_limit", _record)

    assert public_client.get(PUBLIC_ENDPOINT).status_code == 200
    assert recorded["key_prefix"] == RATE_LIMIT_KEY_PREFIX
    assert recorded["identifier"]
    assert recorded["limit"] == 60
    assert recorded["window_seconds"] == 60


def test_endpoint_honours_the_configured_rate_limit(public_client, monkeypatch):
    recorded = {}

    async def _record(**kwargs):
        recorded.update(kwargs)

    monkeypatch.setattr(api_router_module, "enforce_rate_limit", _record)
    monkeypatch.setattr(settings, "RATE_LIMIT_PLANS_PUBLIC", "5/min")

    assert public_client.get(PUBLIC_ENDPOINT).status_code == 200
    assert recorded["limit"] == 5


def test_endpoint_returns_429_when_the_limit_is_exceeded(public_client, monkeypatch):
    from fastapi import HTTPException

    async def _reject(**_kwargs):
        raise HTTPException(status_code=429, detail="Too Many Requests")

    monkeypatch.setattr(api_router_module, "enforce_rate_limit", _reject)

    assert public_client.get(PUBLIC_ENDPOINT).status_code == 429


def test_rate_limit_identifier_uses_the_forwarded_client_ip(public_client, monkeypatch):
    # SIGV2-1243: identity headers only count when the immediate peer is a
    # trusted proxy, so this request comes from a client tuple inside the
    # default private CIDR ranges.
    recorded = {}

    async def _record(**kwargs):
        recorded.update(kwargs)

    monkeypatch.setattr(api_router_module, "enforce_rate_limit", _record)

    trusted_client = TestClient(public_client.app, client=("10.1.2.3", 443))
    trusted_client.get(PUBLIC_ENDPOINT, headers={"x-forwarded-for": "203.0.113.7"})
    assert recorded["identifier"] == "203.0.113.7"


# ===================================================================
# Route-scoped CORS allowance
# ===================================================================


def test_configured_site_origin_is_allowed(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_SITE_ORIGINS", PREPROD_SITE_ORIGIN)
    assert resolve_public_site_origins() == (PREPROD_SITE_ORIGIN,)
    assert is_public_site_origin(PREPROD_SITE_ORIGIN) is True
    assert is_public_site_origin(PREPROD_SITE_ORIGIN + "/") is True


def test_wildcard_is_never_an_allowed_site_origin(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_SITE_ORIGINS", "*")
    assert resolve_public_site_origins() == ()
    assert is_public_site_origin("https://evil.example") is False
    assert is_public_site_origin("*") is False


def test_unset_configuration_allows_nothing(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_SITE_ORIGINS", "")
    assert resolve_public_site_origins() == ()
    assert is_public_site_origin(PREPROD_SITE_ORIGIN) is False


def test_apply_public_site_cors_always_marks_the_response_origin_dependent(monkeypatch):
    from fastapi import Response
    from starlette.datastructures import Headers

    monkeypatch.setattr(settings, "PUBLIC_SITE_ORIGINS", "")

    class _Request:
        headers = Headers({"origin": "https://evil.example"})

    response = Response()
    assert apply_public_site_cors(_Request(), response) is False
    assert response.headers["vary"] == "Origin"
    assert "access-control-allow-origin" not in response.headers


def test_endpoint_allows_the_configured_site_origin(public_client, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_SITE_ORIGINS", PREPROD_SITE_ORIGIN)

    resp = public_client.get(PUBLIC_ENDPOINT, headers={"origin": PREPROD_SITE_ORIGIN})

    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == PREPROD_SITE_ORIGIN


def test_endpoint_refuses_a_disallowed_origin(public_client, monkeypatch):
    """Negative CORS case: a browser on an origin that is not configured gets
    no allowance header, so it cannot read the response."""
    monkeypatch.setattr(settings, "PUBLIC_SITE_ORIGINS", PREPROD_SITE_ORIGIN)

    resp = public_client.get(PUBLIC_ENDPOINT, headers={"origin": "https://evil.example"})

    assert "access-control-allow-origin" not in resp.headers


def test_endpoint_refuses_the_site_origin_when_unconfigured(public_client, monkeypatch):
    """Live is path-shared and therefore same-origin, so with no configuration
    even the real marketing origin gets no cross-origin allowance."""
    monkeypatch.setattr(settings, "PUBLIC_SITE_ORIGINS", "")

    resp = public_client.get(PUBLIC_ENDPOINT, headers={"origin": PREPROD_SITE_ORIGIN})

    assert "access-control-allow-origin" not in resp.headers


def test_site_origin_allowance_does_not_leak_to_other_endpoints(public_client, monkeypatch):
    """The allowance is route scoped: the marketing origin must not become a
    credentialed origin for the rest of the API."""
    monkeypatch.setattr(settings, "PUBLIC_SITE_ORIGINS", PREPROD_SITE_ORIGIN)

    resp = public_client.get(
        "/api/v1/billing/plans",
        headers={"origin": PREPROD_SITE_ORIGIN},
    )

    assert "access-control-allow-origin" not in resp.headers


def test_the_api_row_covers_mcp_on_every_public_plan():
    """SIGV2-1210: one published row, "API & MCP access", must be true of both.

    The MCP server is granted by ``mcp_access`` but advertised through the
    ``api_access`` row, because it is the same surface behind the same API key
    and a second row would read as a second thing to buy. That wording is only
    honest while the two entitlements agree on every plan a customer can see.

    If someone later grants ``api_access`` to a public plan without
    ``mcp_access`` (or the reverse), this fails rather than letting the pricing
    page promise a connection that plan cannot make. The agency trial is
    deliberately excluded: it holds ``api_access`` without ``mcp_access``, and
    it is in ``PRIVATE_PLAN_IDS``, so it never appears on a public surface.
    """
    assert CAPABILITY_DESCRIPTIONS["api_access"] == "API & MCP access"
    # The separate key must stay unpublished, or the matrix grows a second row
    # describing the same purchase.
    assert "mcp_access" in UNPUBLISHED_CAPABILITY_KEYS

    for plan in PUBLIC_PLAN_TYPES:
        assert CAPABILITY_MATRIX[plan]["api_access"] == CAPABILITY_MATRIX[plan]["mcp_access"], (
            f"{plan} grants api_access and mcp_access differently, so the combined "
            '"API & MCP access" row is not true for it'
        )

    # And the gate really is Specialist and up, matching the published row.
    assert MINIMUM_PLAN_BY_FEATURE["mcp_access"] == "plan_specialist"
    assert "plan_agency_trial" in PRIVATE_PLAN_IDS
    assert can_use_feature("plan_agency_trial", "api_access") is True
    assert can_use_feature("plan_agency_trial", "mcp_access") is False
