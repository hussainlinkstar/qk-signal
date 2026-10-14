import logging

from services.hallucination_service import HallucinationService


def test_hallucination_service_flags_field_level_claims_and_omits_low_certainty_narrative() -> None:
    service = HallucinationService(grounding_threshold=0.3, failing_score_threshold=90)
    source_content = (
        "OpenAI released a new model update for coding workflows. "
        "The platform now supports deterministic unit test generation and quick bug triage."
    )
    analysis = {
        "summary": (
            "OpenAI released a new model update for coding workflows. "
            "The platform won a global design award in Paris."
        ),
        "recommendations": ["Use deterministic unit test generation to improve reliability."],
    }

    result = service.analyze(source_content=source_content, analysis=analysis)

    assert result["total_sentences"] == 3
    assert result["supported_sentences"] == 2
    assert result["score"] == 67
    assert result["flagged"] is True
    assert result["omitted_claims"] == 1
    assert "The platform won a global design award in Paris." in result["unsupported_sentences"]
    assert result["claim_verifications"][1]["field_path"] == "summary"
    assert result["claim_verifications"][1]["disposition"] == "omitted"
    assert result["claim_verifications"][1]["certainty_level"] == "high"
    assert result["claim_verifications"][2]["track"] == "track_b"
    assert result["claim_verifications"][2]["claim_kind"] == "prescriptive_recommendation"
    assert "contains_imperative_action" in result["claim_verifications"][2]["classification_basis"]
    assert result["claim_verifications"][2]["omittable"] is True
    assert result["field_summaries"][1]["field_path"] == "summary"
    assert (
        result["sanitized_analysis"]["summary"]
        == "OpenAI released a new model update for coding workflows."
    )
    assert result["sanitized_analysis"]["recommendations"] == [
        "Use deterministic unit test generation to improve reliability."
    ]


def test_hallucination_service_returns_empty_when_no_claims() -> None:
    service = HallucinationService()
    result = service.analyze(source_content="irrelevant", analysis={})

    assert result["score"] == 100
    assert result["flagged"] is False
    assert result["unsupported_sentences"] == []
    assert result["field_summaries"] == []


def test_brand_truth_threshold_behavior() -> None:
    service = HallucinationService(similarity_threshold=0.85)
    analysis = {
        "claims": [
            {"id": "claim-1", "text": "Our headquarters is in Austin Texas."},
            {"id": "claim-2", "text": "We have offices in Berlin Germany."},
        ]
    }
    brand_truth_payload = {
        "truths": {
            "claim-1": "Our headquarters is in Austin Texas.",
            "claim-2": "Our headquarters is in Austin Texas.",
        }
    }

    result = service.analyze(
        source_content="",
        analysis=analysis,
        brand_truth_payload=brand_truth_payload,
    )

    assert result["claim_verifications"][0]["similarity_score"] == 1.0
    assert result["claim_verifications"][0]["hallucination"] is False
    assert result["claim_verifications"][0]["disposition"] == "supported"
    assert result["claim_verifications"][1]["similarity_score"] < 0.85
    assert result["claim_verifications"][1]["hallucination"] is True
    assert result["claim_verifications"][1]["disposition"] == "flagged"


def test_brand_truth_embedding_batching_behavior(monkeypatch) -> None:
    service = HallucinationService(embedding_batch_size=32)
    claims = [{"id": f"claim-{index}", "text": f"Claim text {index}"} for index in range(1, 36)]
    analysis = {"claims": claims}
    brand_truth_payload = {
        "truths": {f"claim-{index}": f"Claim text {index}" for index in range(1, 36)}
    }

    batch_sizes: list[int] = []
    original_embed_batch = service._embed_batch

    def _record_batch(texts: list[str]) -> list[dict[str, float]]:
        batch_sizes.append(len(texts))
        return original_embed_batch(texts)

    monkeypatch.setattr(service, "_embed_batch", _record_batch)

    service.analyze(source_content="", analysis=analysis, brand_truth_payload=brand_truth_payload)

    assert batch_sizes == [32, 3, 32, 3]


def test_brand_truth_audit_log_payload_shape(caplog) -> None:
    service = HallucinationService()
    analysis = {"claims": [{"id": "claim-1", "text": "Our office is in Austin Texas."}]}
    brand_truth_payload = {"truths": {"claim-1": "Our office is in Austin Texas."}}

    with caplog.at_level(logging.INFO):
        service.analyze(
            source_content="", analysis=analysis, brand_truth_payload=brand_truth_payload
        )

    matching_records = [
        record for record in caplog.records if record.msg == "Claim verification audit"
    ]
    assert len(matching_records) == 1
    claim_audit = matching_records[0].claim_audit
    assert set(claim_audit.keys()) == {
        "claim_id",
        "claim_text",
        "matched_truth_key",
        "truth_value",
        "similarity_score",
        "hallucination",
        "discrepancy_type",
        "severity",
        "field_path",
        "field_label",
        "certainty_score",
        "certainty_level",
        "disposition",
        "evidence_refs",
        "track",
        "claim_kind",
        "classification_basis",
        "premise_refs",
        "omittable",
    }
    assert claim_audit["track"] == "track_a"
    assert claim_audit["claim_kind"] == "descriptive_observation"
    assert claim_audit["classification_basis"] == ["asserts_current_state"]


def test_brand_truth_structured_critical_fields_mark_high_severity() -> None:
    service = HallucinationService(similarity_threshold=0.85)
    analysis = {
        "claims": [
            {
                "id": "pricing-1",
                "text": "Starter plan costs $199 per week and includes concierge onboarding.",
            }
        ]
    }
    brand_truth_payload = {
        "critical_fields": {
            "pricing": {
                "pricing-1": "Starter plan costs $49 per month with annual discount.",
            }
        }
    }

    result = service.analyze(
        source_content="", analysis=analysis, brand_truth_payload=brand_truth_payload
    )

    claim = result["claim_verifications"][0]
    assert claim["hallucination"] is True
    assert claim["discrepancy_type"] == "pricing_mismatch"
    assert claim["severity"] == "high"
    assert claim["certainty_level"] == "medium"


def test_rescale_certainty_sigmoid_curve() -> None:
    """Verify the sigmoid maps the narrow TF-IDF range into usable 0-1 scores."""
    rescale = HallucinationService._rescale_certainty

    assert rescale(0.0) == 0.0
    assert rescale(-0.1) == 0.0

    # Very low raw score → low
    assert rescale(0.02) < 0.25

    # Center point (sigmoid centered on raw == 0.10 per AEX-49 calibration) → ~0.50
    center = rescale(0.10)
    assert 0.45 <= center <= 0.55

    # Moderate evidence → well above 0.5
    assert rescale(0.15) > 0.70

    # Strong evidence → near 1.0
    assert rescale(0.25) > 0.90

    # Monotonically increasing
    prev = 0.0
    for raw in [0.01, 0.05, 0.10, 0.13, 0.15, 0.20, 0.30, 0.50]:
        val = rescale(raw)
        assert val > prev, f"rescale({raw})={val} should be > {prev}"
        prev = val


def test_classify_grounded_bidirectional_overlap() -> None:
    """Claims with strong bidirectional token overlap should get higher certainty."""
    service = HallucinationService()

    claim_high = "deterministic unit test generation for coding"
    evidence_high = [
        {
            "excerpt": "deterministic unit test generation and coding workflows",
            "retrieval_score": 0.0,
        }
    ]

    claim_low = "global design award in Paris"
    evidence_low = [
        {
            "excerpt": "platform now supports deterministic unit test generation",
            "retrieval_score": 0.0,
        }
    ]

    _, cert_high, raw_high, _ = service._classify_grounded(claim_high, evidence_high)
    _, cert_low, raw_low, _ = service._classify_grounded(claim_low, evidence_low)

    assert cert_high > cert_low
    assert raw_high > raw_low
