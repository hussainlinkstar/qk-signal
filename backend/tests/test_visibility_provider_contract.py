"""The committed visibility provider contract matches this backend.

SIGV2-1163: the frontend keyed Meta as ``meta_ai``, a value this backend has
never sent, so a real ``meta`` row in ``provider_breakdown`` missed the
frontend's label map, chart colour map and logo map at once. The frontend now
tests its own vocabulary against ``contracts/visibility_providers.json``; this
test is the other half of that loop, and without it the fixture could drift
away from the backend it claims to describe.

The loop:
  1. This test fails if the backend's vocabulary stops matching the fixture, so
     adding or renaming a provider here cannot land without recording it.
  2. ``frontend/src/types/monitoring.providerContract.test.ts`` then fails until
     the frontend handles the newly recorded key.

Only the fixture's ``providers``, ``labels``, ``live_measurable`` and
``live_unavailable`` are the backend's to own. The frontend deliberately shows
different label TEXT and compares keys only.
"""

import json
from pathlib import Path

import pytest

from services.project_visibility_service import (
    LIVE_MEASURABLE_PROVIDERS,
    LIVE_UNAVAILABLE_REASONS,
    OFFERED_VISIBILITY_PROVIDERS,
    SUPPORTED_VISIBILITY_PROVIDERS,
    VISIBILITY_PLAN_LIMITS,
    VISIBILITY_PROVIDER_LABELS,
    WITHDRAWN_VISIBILITY_PROVIDERS,
)

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "contracts" / "visibility_providers.json"


@pytest.fixture(scope="module")
def contract() -> dict:
    assert CONTRACT_PATH.is_file(), f"missing provider contract fixture at {CONTRACT_PATH}"
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_records_the_supported_providers(contract):
    assert contract["providers"] == list(SUPPORTED_VISIBILITY_PROVIDERS)


def test_contract_records_the_provider_labels(contract):
    assert contract["labels"] == VISIBILITY_PROVIDER_LABELS


def test_contract_records_the_live_measurable_providers(contract):
    assert contract["live_measurable"] == list(LIVE_MEASURABLE_PROVIDERS)
    assert contract["live_unavailable"] == LIVE_UNAVAILABLE_REASONS


def test_contract_records_the_withdrawn_providers(contract):
    """SIGV2-1215: the vocabulary and the offer are different lists.

    ``providers`` keeps every key a measurement has ever been recorded under;
    ``offered`` is what the product presents and measures. Recording a
    withdrawal here is what fails the frontend's own contract test until it
    stops rendering the engine.
    """
    assert contract["offered"] == list(OFFERED_VISIBILITY_PROVIDERS)
    assert sorted(contract["withdrawn"]) == sorted(WITHDRAWN_VISIBILITY_PROVIDERS)
    # A withdrawn key stays in the vocabulary and keeps its label, so recorded
    # rows and the retained proxy path still resolve.
    for provider, reason in contract["withdrawn"].items():
        assert provider in contract["providers"], provider
        assert provider in contract["labels"], provider
        assert provider not in contract["offered"], provider
        assert reason.strip(), provider


def test_every_offered_provider_can_be_measured_live(contract):
    """The reason Copilot went: it was the only offered engine with no live
    measurement path. Nothing offered may be in that position again without
    this test being changed on purpose."""
    assert sorted(contract["offered"]) == sorted(contract["live_measurable"])
    assert set(contract["live_unavailable"]) <= set(contract["withdrawn"])


def test_contract_covers_every_entitled_provider(contract):
    """Whatever a plan may be entitled to must be in the recorded vocabulary.

    ``allowed_providers`` is what reaches the frontend on the visibility
    entitlements, so a plan allowed a provider the fixture does not record would
    hand the frontend a key it has never been tested against.

    Since SIGV2-1215 the stronger rule also holds: a plan may only be entitled
    to an OFFERED engine. A roster entry is an offer, and the product cannot
    offer something it does not measure.
    """
    recorded = set(contract["providers"])
    offered = set(contract["offered"])
    for plan, config in VISIBILITY_PLAN_LIMITS.items():
        assert set(config["allowed_providers"]) <= recorded, plan
        assert set(config["allowed_providers"]) <= offered, plan


def test_contract_records_every_plan_roster_and_cadence(contract):
    """SIGV2-1229: the cadence copy is tested against these numbers.

    The competitor gate said the data was "updated daily" while the competitor
    sweep had been weekly since SIGV2-1208. The sentence was a literal, so
    nothing failed when the cadence moved. Recording both cadences here makes
    ``frontend/src/i18n/refreshCadenceCopy.test.ts`` derive the word from the
    interval, and makes this test the thing that fails if a cadence changes
    without the fixture, exactly as the provider vocabulary works above.
    """
    assert set(contract["plans"]) == set(VISIBILITY_PLAN_LIMITS)
    for plan, config in VISIBILITY_PLAN_LIMITS.items():
        recorded = contract["plans"][plan]
        assert recorded["allowed_providers"] == list(config["allowed_providers"]), plan
        assert recorded["sweep_interval_seconds"] == config["sweep_interval_seconds"], plan
        assert (
            recorded["competitor_sweep_interval_seconds"]
            == config["competitor_sweep_interval_seconds"]
        ), plan


def test_meta_is_keyed_meta_not_meta_ai(contract):
    """The specific drift this contract exists to stop coming back."""
    assert "meta" in SUPPORTED_VISIBILITY_PROVIDERS
    assert "meta_ai" not in SUPPORTED_VISIBILITY_PROVIDERS
    assert "meta_ai" not in contract["providers"]
    assert "meta_ai" not in contract["labels"]
