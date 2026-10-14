from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
_SKILLS_DIR = _PROMPTS_DIR / "skills"

_ROLE_DOMAIN_KEYS: dict[tuple[str, str], str] = {
    ("smart", "seo_generator"): "seo",
    ("smart", "aeo_geo_generator"): "aeo_geo",
    ("deep_judgment", "seo_generator"): "seo",
    ("deep_judgment", "geo_generator"): "geo",
    ("deep_judgment", "aeo_generator"): "aeo",
    ("deep_judgment", "seo_critic"): "seo",
    ("deep_judgment", "geo_critic"): "geo",
    ("deep_judgment", "aeo_critic"): "aeo",
}

_DOMAIN_EXCLUSION_RULES: dict[str, list[str]] = {
    "seo": [
        "Entity recognition, Knowledge Graph coverage, and organization authority scoring",
        "Brand authority, NAP consistency, local-pack presence, and geographic trust signals",
        "Citation probability scoring, featured-snippet targeting, and conversational answer design",
    ],
    "geo": [
        "Technical crawlability, indexation, Core Web Vitals, and non-entity schema fixes",
        "Featured-snippet tactics, FAQ/HowTo answer formatting, and conversational answer readiness",
    ],
    "aeo": [
        "Technical crawlability, indexation, Core Web Vitals, and general on-page SEO fixes",
        "Entity graph modeling, organization authority, brand trust, and local presence management",
    ],
    "aeo_geo": [
        "Technical crawlability, indexation, Core Web Vitals, backlink remediation, and generic on-page SEO fixes",
    ],
}

_ROLE_SKILL_MAP: dict[tuple[str, str], list[str]] = {
    ("fast", "proposer"): [
        "seo_onpage_auditor",
        "aeo_answer_engine_auditor",
        "geo_brand_entity_auditor",
    ],
    ("smart", "seo_generator"): [
        "seo_onpage_auditor",
        "technical_seo_auditor",
        "link_authority_auditor",
    ],
    ("smart", "aeo_geo_generator"): [
        "aeo_answer_engine_auditor",
        "geo_brand_entity_auditor",
        "schema_structured_data_reviewer",
    ],
    ("deep_judgment", "seo_generator"): [
        "seo_onpage_auditor",
        "technical_seo_auditor",
        "serp_snippet_optimizer",
    ],
    ("deep_judgment", "geo_generator"): [
        "geo_brand_entity_auditor",
        "schema_structured_data_reviewer",
        "content_quality_evaluator",
    ],
    ("deep_judgment", "aeo_generator"): [
        "aeo_answer_engine_auditor",
        "ai_crawler_readiness",
        "serp_snippet_optimizer",
    ],
}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is None or value == "":
            continue
        # Skip empty collections so callers fall through to the next source.
        if isinstance(value, (list, dict, tuple, set)) and len(value) == 0:
            continue
        return value
    return None


def _dig(payload: dict[str, Any] | None, *path: str) -> Any:
    current: Any = payload or {}
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


@lru_cache(maxsize=64)
def load_prompt_template(tier: str, role: str) -> str:
    path = _PROMPTS_DIR / str(tier).strip() / f"{str(role).strip()}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=32)
def load_shared_template(name: str) -> str:
    path = _PROMPTS_DIR / "shared" / f"{str(name).strip()}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Shared prompt template not found: {path}")
    return path.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=32)
def load_skill(name: str) -> str:
    path = _SKILLS_DIR / f"{str(name).strip()}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Skill file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def load_skills_for_role(tier: str, role: str) -> str:
    key = (str(tier).strip(), str(role).strip())
    skill_names = _ROLE_SKILL_MAP.get(key, [])
    if not skill_names:
        return ""
    sections = []
    for name in skill_names:
        try:
            sections.append(load_skill(name))
        except FileNotFoundError:
            logger.warning("Skill file %s not found for role %s/%s", name, tier, role)
    if not sections:
        return ""
    return (
        "## Domain Evaluation Skills\n"
        "Use the following evaluation frameworks to guide your analysis. "
        "Apply signal checklists to the evidence, respect false-positive guards, "
        "and adapt evaluation to the detected page type.\n\n" + "\n\n---\n\n".join(sections)
    )


def build_evidence_anchor(audit_data: dict[str, Any]) -> dict[str, Any]:
    context_payload = (
        audit_data.get("context_payload")
        if isinstance(audit_data.get("context_payload"), dict)
        else {}
    )
    analysis_payload = (
        audit_data.get("analysis") if isinstance(audit_data.get("analysis"), dict) else {}
    )
    network_data = (
        audit_data.get("network_data") if isinstance(audit_data.get("network_data"), dict) else {}
    )

    core_web_vitals = _coalesce(
        audit_data.get("core_web_vitals"),
        _dig(network_data, "core_web_vitals"),
        _dig(context_payload, "core_web_vitals"),
        {},
    )
    schema_types = _coalesce(
        audit_data.get("schema_types"),
        _dig(context_payload, "schema_structure", "detected_schema_types"),
        _dig(context_payload, "schema_types"),
        _dig(analysis_payload, "schema_types_found"),
        [],
    )

    return {
        "scores": {
            "seo": _coalesce(audit_data.get("seo_score"), _dig(analysis_payload, "seo_score")),
            "geo": _coalesce(audit_data.get("geo_score"), _dig(analysis_payload, "geo_score")),
            "aeo": _coalesce(audit_data.get("aeo_score"), _dig(analysis_payload, "aeo_score")),
        },
        "critical_metrics": {
            "pages_crawled": _coalesce(
                audit_data.get("pages_crawled"),
                _dig(network_data, "pages_crawled"),
                _dig(context_payload, "pages_crawled"),
            ),
            "schema_types_found": schema_types if isinstance(schema_types, list) else [],
            "thin_content": _dig(context_payload, "thin_content") or None,
            "core_web_vitals": core_web_vitals if isinstance(core_web_vitals, dict) else {},
            "backlinks_count": _coalesce(
                audit_data.get("backlinks_count"),
                _dig(context_payload, "backlinks_count"),
            ),
            "indexed_pages": _coalesce(
                audit_data.get("indexed_pages"),
                _dig(context_payload, "indexed_pages"),
            ),
            "domain_authority": _safe_float(
                _coalesce(
                    audit_data.get("domain_authority"),
                    _dig(context_payload, "domain_authority"),
                )
            ),
            "total_queries_analyzed": _coalesce(
                audit_data.get("total_queries_analyzed"),
                _dig(context_payload, "total_queries_analyzed"),
            ),
            "citation_presence_rate": _safe_float(
                _coalesce(
                    audit_data.get("citation_presence_rate"),
                    _dig(context_payload, "citation_presence_rate"),
                )
            ),
        },
        "scan_timestamp": _coalesce(
            audit_data.get("scan_timestamp"),
            _dig(context_payload, "scan_timestamp"),
        ),
    }


def render_evidence_anchor_block(audit_data: dict[str, Any]) -> str:
    anchor = build_evidence_anchor(audit_data)
    return (
        "## Evidence Anchor (DO NOT IGNORE)\n"
        "The following metrics are GROUND TRUTH extracted directly from audit data.\n"
        "Use them to verify claims made by other agents. If a claim contradicts these metrics,\n"
        "flag it as unsupported or route it to manual review.\n\n"
        f"```json\n{json.dumps(anchor, indent=2, ensure_ascii=True, default=str)}\n```"
    )


def build_domain_exclusion_list(domain_key: str | None) -> str:
    rules = _DOMAIN_EXCLUSION_RULES.get(str(domain_key or "").strip().lower(), [])
    if not rules:
        return "- No domain exclusion list is defined for this role."
    return "\n".join(f"- {rule}" for rule in rules)


def load_prompt_with_context(
    tier: str,
    role: str,
    *,
    audit_data: dict[str, Any] | None = None,
    extra_placeholders: dict[str, str] | None = None,
) -> str:
    template = load_prompt_template(tier, role)
    replacements = {
        "{evidence_anchor}": render_evidence_anchor_block(audit_data or {}),
        "{output_format_rules}": load_shared_template("output_format_rules"),
        "{claim_ledger_instructions}": load_shared_template("claim_ledger_instructions"),
        "{schema_awareness_rules}": load_shared_template("schema_awareness_rules"),
        "{finding_quality_rules}": load_shared_template("finding_quality_rules"),
        "{domain_exclusion_list}": build_domain_exclusion_list(
            _ROLE_DOMAIN_KEYS.get((str(tier).strip(), str(role).strip()))
        ),
        "{domain_skills}": load_skills_for_role(tier, role),
        "{critique_rubric}": load_shared_template("critique_rubric"),
    }
    for key, value in (extra_placeholders or {}).items():
        replacements[f"{{{key}}}"] = str(value)

    rendered = template
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    return rendered
