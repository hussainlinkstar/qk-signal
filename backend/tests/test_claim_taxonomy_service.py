from services.claim_taxonomy_service import (
    CLAIM_KIND_DESCRIPTIVE_OBSERVATION,
    CLAIM_KIND_MIXED,
    CLAIM_KIND_PRESCRIPTIVE_RECOMMENDATION,
    ClaimTaxonomyService,
    TRACK_A,
    TRACK_B,
    TRACK_MIXED,
)


def test_claim_taxonomy_classifies_normative_examples() -> None:
    service = ClaimTaxonomyService()

    expectations = [
        (
            "The homepage does not mention Romania in the H1 or hero copy.",
            TRACK_A,
            CLAIM_KIND_DESCRIPTIVE_OBSERVATION,
            {"asserts_absence", "asserts_current_state"},
        ),
        (
            "The site lacks FAQ schema on the homepage.",
            TRACK_A,
            CLAIM_KIND_DESCRIPTIVE_OBSERVATION,
            {"asserts_absence", "asserts_current_state"},
        ),
        (
            "The site serves weddings in Romania.",
            TRACK_A,
            CLAIM_KIND_DESCRIPTIVE_OBSERVATION,
            {"asserts_current_state"},
        ),
        (
            "Add FAQ schema to the homepage to improve answer extraction.",
            TRACK_B,
            CLAIM_KIND_PRESCRIPTIVE_RECOMMENDATION,
            {"contains_imperative_action"},
        ),
        (
            "Add a local-market modifier to the H1 if Romania is a supported market.",
            TRACK_B,
            CLAIM_KIND_PRESCRIPTIVE_RECOMMENDATION,
            {"contains_imperative_action", "conditional_on_authoritative_metadata"},
        ),
        (
            "No dedicated local-market landing page was found in the crawl.",
            TRACK_A,
            CLAIM_KIND_DESCRIPTIVE_OBSERVATION,
            {"asserts_absence", "asserts_current_state"},
        ),
        (
            "The H1 should include Wedding Planning Romania.",
            TRACK_B,
            CLAIM_KIND_PRESCRIPTIVE_RECOMMENDATION,
            {"contains_imperative_action", "contains_unsupported_concrete_token"},
        ),
    ]

    for text, expected_track, expected_kind, expected_basis in expectations:
        annotated = service.annotate_claim({"id": "claim-1", "text": text, "field_group": "claims"})

        assert annotated["track"] == expected_track
        assert annotated["claim_kind"] == expected_kind
        assert expected_basis.issubset(set(annotated["classification_basis"]))


def test_claim_taxonomy_marks_mixed_claims_and_can_atomize_them() -> None:
    service = ClaimTaxonomyService()
    claim = {
        "id": "claim-7",
        "text": "Because the business has a Paris branch, create a Paris FAQ page.",
        "field_group": "recommendations",
        "field_label": "Recommendations 1",
        "field_path": "recommendations[0]",
    }

    annotated = service.annotate_claim(claim)

    assert annotated["track"] == TRACK_MIXED
    assert annotated["claim_kind"] == CLAIM_KIND_MIXED
    assert "mixed_fact_and_prescription" in annotated["classification_basis"]

    atomized = service.atomize_claim(claim)

    assert len(atomized) == 2
    assert atomized[0]["track"] == TRACK_A
    assert atomized[0]["claim_kind"] == CLAIM_KIND_DESCRIPTIVE_OBSERVATION
    assert atomized[0]["text"] == "the business has a Paris branch."
    assert atomized[1]["track"] == TRACK_B
    assert atomized[1]["claim_kind"] == CLAIM_KIND_PRESCRIPTIVE_RECOMMENDATION
    assert atomized[1]["text"] == "create a Paris FAQ page."
    assert atomized[1]["premise_refs"] == ["claim-7-a"]


def test_claim_taxonomy_unsplittable_mixed_claim_defaults_to_track_a() -> None:
    service = ClaimTaxonomyService()

    atomized = service.atomize_claim(
        {
            "id": "claim-9",
            "text": "The site has a Paris branch and should create a Paris FAQ page.",
            "field_group": "recommendations",
        }
    )

    assert len(atomized) == 1
    assert atomized[0]["track"] == TRACK_A
    assert atomized[0]["claim_kind"] == CLAIM_KIND_DESCRIPTIVE_OBSERVATION
    assert "mixed_unsplittable_defaults_to_track_a" in atomized[0]["classification_basis"]
