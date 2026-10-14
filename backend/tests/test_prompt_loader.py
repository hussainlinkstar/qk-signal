from pathlib import Path
import sys

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.prompt_loader import (
    _PROMPTS_DIR,
    _SKILLS_DIR,
    _ROLE_SKILL_MAP,
    build_domain_exclusion_list,
    build_evidence_anchor,
    load_prompt_template,
    load_prompt_with_context,
    load_shared_template,
    load_skill,
    load_skills_for_role,
)


def test_load_prompt_template_reads_v3_prompt_file() -> None:
    prompt = load_prompt_template("smart", "seo_generator")
    assert "SEO Generator" in prompt
    assert "{evidence_anchor}" in prompt


def test_load_prompt_template_raises_for_missing_prompt() -> None:
    with pytest.raises(FileNotFoundError):
        load_prompt_template("smart", "missing_role")


def test_build_evidence_anchor_extracts_ground_truth_metrics() -> None:
    anchor = build_evidence_anchor(
        {
            "seo_score": 61,
            "geo_score": 52,
            "aeo_score": 48,
            "pages_crawled": 847,
            "schema_types": ["Article", "FAQPage"],
            "core_web_vitals": {"LCP": 3.2},
            "backlinks_count": 1243,
            "indexed_pages": 612,
            "domain_authority": 34,
            "total_queries_analyzed": 25,
            "citation_presence_rate": 0.12,
            "scan_timestamp": "2026-03-13T18:00:00Z",
        }
    )

    assert anchor["scores"] == {"seo": 61, "geo": 52, "aeo": 48}
    assert anchor["critical_metrics"]["pages_crawled"] == 847
    assert anchor["critical_metrics"]["schema_types_found"] == ["Article", "FAQPage"]
    assert anchor["critical_metrics"]["core_web_vitals"] == {"LCP": 3.2}
    assert anchor["scan_timestamp"] == "2026-03-13T18:00:00Z"


def test_build_domain_exclusion_list_varies_by_domain() -> None:
    seo_exclusions = build_domain_exclusion_list("seo")
    geo_exclusions = build_domain_exclusion_list("geo")

    assert "Knowledge Graph" in seo_exclusions
    assert "Core Web Vitals" in geo_exclusions
    assert seo_exclusions != geo_exclusions


def test_load_prompt_with_context_injects_anchor_shared_rules_and_domain_boundary() -> None:
    rendered = load_prompt_with_context(
        "deep_judgment",
        "seo_generator",
        audit_data={
            "seo_score": 62,
            "pages_crawled": 128,
            "context_payload": {"scan_timestamp": "2026-03-16T10:00:00Z"},
        },
    )

    assert "Evidence Anchor (DO NOT IGNORE)" in rendered
    assert '"seo": 62' in rendered
    assert "NOT Your Domain" in rendered
    assert "Knowledge Graph" in rendered
    assert "Return ONLY valid JSON" in rendered
    assert "claim_id" in rendered


def test_v3_prompt_tree_exists_on_disk() -> None:
    expected_paths = [
        _PROMPTS_DIR / "fast" / "proposer.md",
        _PROMPTS_DIR / "smart" / "seo_generator.md",
        _PROMPTS_DIR / "deep_judgment" / "global_magistrate.md",
        _PROMPTS_DIR / "shared" / "output_format_rules.md",
    ]

    for path in expected_paths:
        assert isinstance(path, Path)
        assert path.is_file()


# ---------------------------------------------------------------------------
#  load_skill
# ---------------------------------------------------------------------------


def test_load_skill_returns_content() -> None:
    text = load_skill("seo_onpage_auditor")
    assert len(text) > 50
    assert "SEO" in text.upper() or "seo" in text.lower()


def test_load_skill_raises_for_missing_skill() -> None:
    with pytest.raises(FileNotFoundError, match="Skill file not found"):
        load_skill("totally_made_up_skill_xyz")


# ---------------------------------------------------------------------------
#  load_shared_template
# ---------------------------------------------------------------------------


def test_load_shared_template_returns_content() -> None:
    text = load_shared_template("output_format_rules")
    assert len(text) > 20
    assert "JSON" in text or "json" in text.lower()


def test_load_shared_template_raises_for_missing() -> None:
    with pytest.raises(FileNotFoundError, match="Shared prompt template not found"):
        load_shared_template("nonexistent_template_xyz")


# ---------------------------------------------------------------------------
#  load_skills_for_role
# ---------------------------------------------------------------------------


def test_load_skills_for_role_returns_header_and_content_for_known_role() -> None:
    text = load_skills_for_role("fast", "proposer")
    assert text.startswith("## Domain Evaluation Skills")
    assert len(text) > 100


def test_load_skills_for_role_returns_empty_for_unknown_role() -> None:
    text = load_skills_for_role("fast", "nonexistent_role")
    assert text == ""


def test_load_skills_for_role_returns_empty_for_unmapped_tier() -> None:
    text = load_skills_for_role("lite", "proposer")
    assert text == ""


# ---------------------------------------------------------------------------
#  Skill file existence — every skill referenced in _ROLE_SKILL_MAP must exist
# ---------------------------------------------------------------------------


def test_all_referenced_skill_files_exist_on_disk() -> None:
    all_skills = set()
    for skill_names in _ROLE_SKILL_MAP.values():
        all_skills.update(skill_names)

    missing = []
    for skill_name in sorted(all_skills):
        path = _SKILLS_DIR / f"{skill_name}.md"
        if not path.is_file():
            missing.append(skill_name)
    assert missing == [], f"Missing skill files: {missing}"


def test_all_shared_templates_referenced_by_loader_exist() -> None:
    expected = [
        "output_format_rules",
        "claim_ledger_instructions",
        "schema_awareness_rules",
        "finding_quality_rules",
        "critique_rubric",
    ]
    missing = []
    for name in expected:
        path = _PROMPTS_DIR / "shared" / f"{name}.md"
        if not path.is_file():
            missing.append(name)
    assert missing == [], f"Missing shared templates: {missing}"
