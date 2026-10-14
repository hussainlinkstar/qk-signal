"""The audit model selection is server-owned on every plan (SIGV2-1139).

Three statements about provider choice used to disagree: the start-scan screen
told a Standard customer that choosing providers was theirs, the screen offered
no control, and the API discarded any selection that was submitted. The
resolution is that nobody can choose: no plan in the catalogue grants a model
choice, the Enterprise tier the old gate was named after was removed from the
product, and there has been no provider control in the UI since the start-scan
rebuild (SIGV2-1113 deleted ``ProviderPicker``).

SIGV2-1120 then deleted the ``has_custom_ai_model_routing`` capability key
itself, which had survived as an always-``False`` entry in five plan matrices,
the pricing matrix, the admin descriptions and the frontend comparison table.
Nothing read it, so removing it moved no entitlement, but while it existed it
read as a capability the product sells. The first class below was retargeted
from "the key is false everywhere" to "the key is absent everywhere".

These tests pin all three places together, so the copy and the gate cannot
drift apart again:

* no plan grants the capability, and no Enterprise plan exists to grant it;
* the API strip discards a submitted selection unconditionally;
* the customer-facing note on the start-scan screen names no plan as granting
  a choice, in both shipped locales.

The strip and copy classes are deliberately unchanged by SIGV2-1120. They are
the only coverage of ``_strip_client_model_selection``, which is live on three
endpoints, and ``test_multi_model_consensus_cannot_be_forced_by_a_caller``
guards a real cost-abuse vector where a caller forces the expensive consensus
path. Deleting this file with the retired gate would have lost that.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from app.config.plans import (
    CANONICAL_PLAN_TYPES,
    CAPABILITY_DESCRIPTIONS,
    CAPABILITY_MATRIX,
    MINIMUM_PLAN_BY_FEATURE,
    PLAN_PRESENTATION,
    can_use_feature,
)
from app.services.compliance.plan_validator import PlanValidator
from database import Base

# The gate function under test
from routers.api_router import _strip_client_model_selection


ROUTING_CAPABILITY = "has_custom_ai_model_routing"
REPO_ROOT = Path(__file__).resolve().parents[2]
I18N_FILES = (
    REPO_ROOT / "frontend" / "src" / "i18n" / "en.json",
    REPO_ROOT / "frontend" / "src" / "i18n" / "ar.json",
)


# ── Helpers ───────────────────────────────────────────────────────────────


def _build_user(plan_type: str):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    user = models.User(
        email=f"routing-{plan_type}@example.com",
        hashed_password="not-a-real-hash",
        role="user",
        credits=500,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    sub = models.Subscription(
        user_id=user.id,
        stripe_customer_id=f"cus_{plan_type}",
        stripe_subscription_id=f"sub_{plan_type}",
        plan_type=plan_type,
        status="active",
    )
    db.add(sub)
    db.commit()
    db.refresh(user)

    return db, user


def _model_note(locale_file: Path) -> str:
    payload = json.loads(locale_file.read_text(encoding="utf-8"))
    return str(payload["signalStartCheck"]["models"]["planNote"])


# ── The entitlement: nobody is granted a model choice ─────────────────────


class TestNoPlanGrantsModelRouting:
    """SIGV2-1120 changed what this class pins, not whether it pins it.

    Until SIGV2-1120 the capability key existed and was ``False`` on every
    plan, so these tests asserted the value. The key is now deleted from
    ``CAPABILITY_MATRIX``, ``CAPABILITY_DESCRIPTIONS``, the pricing matrix and
    the frontend, because an always-false key nothing reads still advertises a
    capability the product does not have, which is the confusion that produced
    the original defect. The assertions therefore moved from "the key is
    false" to "the key is absent, and absence denies", which is the stronger
    of the two: ``can_use_feature`` and ``PlanValidator.has_feature`` both
    resolve an unknown key through ``.get(key, False)``, so the denial below
    is a property of the lookup rather than of a value someone could flip.
    """

    @pytest.mark.parametrize("plan", CANONICAL_PLAN_TYPES)
    def test_capability_is_absent_from_every_plan(self, plan: str):
        """The key is gone from the matrix, not merely set to ``False``."""
        assert ROUTING_CAPABILITY not in CAPABILITY_MATRIX[plan]

    def test_capability_has_no_description(self):
        """No admin or public catalogue row can render a label for it."""
        assert ROUTING_CAPABILITY not in CAPABILITY_DESCRIPTIONS

    def test_capability_has_no_minimum_plan(self):
        """No plan ladder entry, so ``can_use_feature`` has no fallback grant."""
        assert ROUTING_CAPABILITY not in MINIMUM_PLAN_BY_FEATURE

    @pytest.mark.parametrize("plan", CANONICAL_PLAN_TYPES)
    def test_can_use_feature_denies_every_plan(self, plan: str):
        assert can_use_feature(plan, ROUTING_CAPABILITY) is False

    @pytest.mark.parametrize("plan", CANONICAL_PLAN_TYPES)
    def test_plan_validator_denies_a_real_subscriber(self, plan: str):
        db, user = _build_user(plan)
        try:
            assert PlanValidator().has_feature(user, ROUTING_CAPABILITY) is False
        finally:
            db.close()

    def test_catalogue_has_no_enterprise_plan(self):
        """The tier the old gate was named after is not purchasable.

        The Global Enterprise plan was removed from the product; alembic
        ``20260731_010000_narrow_subscription_plan_type_constraint`` keeps
        ``plan_global_enterprise`` only as a legacy allowed value. The
        catalogue tops out at ``plan_executive``.
        """
        assert not [plan for plan in CANONICAL_PLAN_TYPES if "enterprise" in plan]
        assert not [
            presentation["name"]
            for presentation in PLAN_PRESENTATION.values()
            if "enterprise" in presentation["name"].lower()
        ]


# ── The gate: the strip is unconditional ──────────────────────────────────


class TestStripClientModelSelection:
    def test_none_inputs_pass_through(self):
        assert _strip_client_model_selection(provider=None, selected_models=None) == (None, None)

    def test_submitted_provider_is_discarded(self):
        assert _strip_client_model_selection(provider="anthropic", selected_models=None) == (
            None,
            None,
        )

    def test_submitted_models_are_discarded(self):
        assert _strip_client_model_selection(
            provider=None,
            selected_models=["google", "openai"],
        ) == (None, None)

    def test_submitted_provider_and_models_are_discarded(self):
        assert _strip_client_model_selection(
            provider="anthropic",
            selected_models=["anthropic", "openai"],
        ) == (None, None)

    def test_multi_model_consensus_cannot_be_forced_by_a_caller(self):
        """Two or more surviving models switch the forecast to consensus mode.

        ``services.cost_forecast_service`` selects ``multi_model_consensus``
        as soon as the route carries two models, which is one LLM step per
        model plus a synthesis step. The strip is the barrier, so it is pinned
        for a request that asks for the whole provider set.
        """
        _, models_out = _strip_client_model_selection(
            provider="openai",
            selected_models=["openai", "anthropic", "google", "perplexity", "xai", "deepseek"],
        )
        assert models_out is None

    def test_granting_the_capability_does_not_reopen_routing(self, monkeypatch):
        """The strip does not consult the capability, by decision.

        Flipping the flag back on in the matrix must not silently re-grant a
        per-scan model choice behind copy that says there is nothing to choose.
        Un-retiring the capability means changing this test, the note and the
        UI together.
        """
        monkeypatch.setitem(CAPABILITY_MATRIX["plan_executive"], ROUTING_CAPABILITY, True)
        assert _strip_client_model_selection(
            provider="anthropic",
            selected_models=["anthropic", "openai"],
        ) == (None, None)


# ── The copy: the screen may not name a plan it cannot honour ─────────────


class TestStartScanModelNote:
    @pytest.mark.parametrize("locale_file", I18N_FILES, ids=lambda path: path.stem)
    def test_note_exists_in_every_shipped_locale(self, locale_file: Path):
        assert _model_note(locale_file).strip()

    @pytest.mark.parametrize("locale_file", I18N_FILES, ids=lambda path: path.stem)
    def test_note_names_no_plan_while_no_plan_grants_a_choice(self, locale_file: Path):
        """The defect was a plan name in copy the backend did not honour.

        While ``has_custom_ai_model_routing`` is granted by nothing, the note
        must not attribute a model choice to any plan. ``plan_standard`` is the
        one this shipped with ("Choosing providers is a Standard feature"), and
        the Arabic copy carried the same Latin plan name.
        """
        assert not any(
            can_use_feature(plan, ROUTING_CAPABILITY) for plan in CANONICAL_PLAN_TYPES
        ), "a plan now grants model routing: revisit this note and the UI before relaxing the pin"

        note = _model_note(locale_file)
        for presentation in PLAN_PRESENTATION.values():
            assert presentation["name"].lower() not in note.lower(), (
                f"the model selection note names the {presentation['name']} plan, "
                "but no plan grants a model choice"
            )
