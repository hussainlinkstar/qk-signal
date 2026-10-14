"""Guest-audit lock metadata must only advertise capabilities that exist.

A ``locked_sections`` entry exists to tell a prospect what signing up would
unlock. Before SIGV2-1152 the guest pipeline hand-wrote that metadata and
advertised three capability keys that no plan defines (``has_geo_analysis``,
``has_aeo_analysis``, ``has_hallucination_analysis``) together with
hand-written required plans that disagreed with ``MINIMUM_PLAN_BY_FEATURE``.
Nothing failed, because no test enumerated the advertised keys.

These tests enumerate them, so a future hand-written key is caught here
instead of by inspection.
"""

from __future__ import annotations

from app.config.plans import (
    CANONICAL_PLAN_TYPES,
    CAPABILITY_MATRIX,
    MINIMUM_PLAN_BY_FEATURE,
    PLAN_PRESENTATION,
    can_use_feature,
)
from services.audit_feature_gating_service import build_lock_metadata
from services.guest_audit_service import GUEST_LOCKED_SECTION_CAPABILITIES


def _all_matrix_keys() -> set[str]:
    keys: set[str] = set()
    for capabilities in CAPABILITY_MATRIX.values():
        keys.update(capabilities)
    return keys


def test_every_advertised_capability_key_exists_in_the_matrix() -> None:
    matrix_keys = _all_matrix_keys()
    unknown = {
        section: capability
        for section, capability in GUEST_LOCKED_SECTION_CAPABILITIES.items()
        if capability not in matrix_keys
    }
    assert unknown == {}, (
        "guest lock metadata advertises capability keys no plan defines: "
        f"{unknown}. A lock card is a plan promise, so every advertised key "
        "must exist in CAPABILITY_MATRIX."
    )


def test_every_advertised_capability_key_is_defined_on_every_plan() -> None:
    # A key present on only some plans would make the advertised promise
    # depend on which plan happens to carry it.
    for section, capability in GUEST_LOCKED_SECTION_CAPABILITIES.items():
        for plan in CANONICAL_PLAN_TYPES:
            assert capability in CAPABILITY_MATRIX[plan], (section, capability, plan)


def test_every_advertised_capability_declares_a_minimum_plan() -> None:
    missing = sorted(
        capability
        for capability in GUEST_LOCKED_SECTION_CAPABILITIES.values()
        if capability not in MINIMUM_PLAN_BY_FEATURE
    )
    assert missing == [], (
        "guest lock metadata cannot state a required plan for "
        f"{missing}: add the capability to MINIMUM_PLAN_BY_FEATURE rather "
        "than hand-writing a plan name on the lock card."
    )


def test_lock_metadata_required_plan_is_derived_not_hand_written() -> None:
    for section, capability in GUEST_LOCKED_SECTION_CAPABILITIES.items():
        metadata = build_lock_metadata(
            capability_key=capability,
            detail="detail",
            lock_origin="guest",
        )
        expected_plan = MINIMUM_PLAN_BY_FEATURE[capability]
        assert metadata["capability_key"] == capability, section
        assert metadata["required_plan"] == expected_plan, section
        assert metadata["required_plan_label"] == PLAN_PRESENTATION[expected_plan]["name"], section
        assert metadata["is_locked"] is True, section
        assert metadata["lock_origin"] == "guest", section


def test_advertised_required_plan_actually_grants_the_capability() -> None:
    # The whole point of the lock card: the named plan must really unlock it.
    for section, capability in GUEST_LOCKED_SECTION_CAPABILITIES.items():
        required_plan = MINIMUM_PLAN_BY_FEATURE[capability]
        assert can_use_feature(required_plan, capability) is True, (section, capability)


def test_guest_lock_sections_are_the_expected_set() -> None:
    # Guards against a section being silently dropped or added without the
    # capability mapping being reviewed.
    assert set(GUEST_LOCKED_SECTION_CAPABILITIES) == {
        "geo",
        "aeo",
        "competitors",
        "entities",
        "hallucinations",
        "export",
    }
