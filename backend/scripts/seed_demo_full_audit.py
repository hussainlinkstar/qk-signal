"""Fill the local demo project's audits with a complete, consistent report.

Local development only. The demo audits store two or three metrics per pillar,
and the normalisation layer pads the rest of the canonical schema with zeros, so
the detail screens show "0" for metrics that were never measured rather than
saying they are absent. That makes it impossible to review those screens, which
is what this script is for: it writes a full canonical report so every panel,
table and chart has something truthful to render in review.

Values are demo values and are labelled as such in `metadata.demo_seed`. Run it
against a local database only. It refuses to touch anything that does not look
like the local demo project.

    docker compose exec -T backend python scripts/seed_demo_full_audit.py
"""

from __future__ import annotations

import pathlib
import sys

# Run from scripts/ as well as from the backend root.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import database  # noqa: E402
import models  # noqa: E402

from _demo_seed_guard import assert_local_database  # noqa: E402

PROJECT_ID = 1
EXPECTED_DOMAIN = "qiko.ai"

# One entry per audit, oldest first, so the dashboard trend rises the way the
# stored headline scores already do (SEO 58 to 72, AEO 50 to 61, GEO 44 to 61).
PROGRESSION = [
    {"seo": 58, "aeo": 50, "geo": 44},
    {"seo": 62, "aeo": 54, "geo": 48},
    {"seo": 65, "aeo": 57, "geo": 51},
    {"seo": 68, "aeo": 60, "geo": 54},
    {"seo": 70, "aeo": 62, "geo": 56},
    {"seo": 71, "aeo": 63, "geo": 57},
    {"seo": 72, "aeo": 61, "geo": 61},
]


def _scale(base: int, offset: int) -> float:
    """A component score near the pillar score, clamped to 0-100.

    Returned as a float: the canonical pillar models are `strict=True`, so a
    `NonNegativeFloat` field rejects an int outright.
    """
    return float(max(0, min(100, base + offset)))


def seo_block(seo: int) -> dict:
    return {
        "onpage": _scale(seo, -2),
        "performance": _scale(seo, -9),
        "indexing": _scale(seo, 6),
        "core_web_vitals": _scale(seo, -11),
        "technical_seo": _scale(seo, 4),
        "onpage_content": _scale(seo, -4),
        "eeat_trust": _scale(seo, -14),
        "security_accessibility": _scale(seo, 9),
    }


def aeo_block(aeo: int) -> dict:
    return {
        "answerability_score": _scale(aeo, 3),
        "extractable_pages": 9,
        # Dicts, not scores: the canonical model carries the audit detail here.
        "schema_health": {"pages_with_schema": 9, "pages_checked": 14, "errors": 2},
        "schema_coverage": {"faq": True, "howto": False, "organization": True},
        # A ratio, capped at 1 by the model, not a 0-100 score.
        "readability_score": round(min(1.0, _scale(aeo, 12) / 100), 2),
        "readability_findings": [
            "Pricing page: three sentences over 40 words",
            "Home hero: nested clauses reduce extract quality",
            "Docs intro: passive voice in the opening paragraph",
            "Labs page: undefined acronym on first use",
        ],
        "rewrite_suggestions": [
            {"page": "/pricing", "change": "Split the plan comparison into one claim per sentence"},
            {"page": "/", "change": "Lead the hero with the outcome, not the mechanism"},
        ],
        "llm_schema_readiness": _scale(aeo, -8),
        "semantic_entity_density": _scale(aeo, -3),
        "information_gain": _scale(aeo, 5),
        "snippet_formatting": _scale(aeo, -10),
    }


def geo_block(geo: int) -> dict:
    return {
        "visibility_index": _scale(geo, -3),
        # 0-100 in the canonical model, not a ratio.
        "citation_share": _scale(geo, -18),
        "brand_anchor": _scale(geo, -11),
        "advanced_local_schema": _scale(geo, 8),
        "napw_completeness": _scale(geo, 14),
        "spatial_content": _scale(geo, -12),
        "brand_citation": _scale(geo, -6),
        "content_citability": _scale(geo, 2),
        "source_authority": _scale(geo, -9),
        "entity_clarity": _scale(geo, 5),
    }


# `entities` is a list of plain strings on the canonical model, not objects.
ENTITIES = ["Qiko", "Qiko Signal", "Qiko Labs", "AI visibility", "answer engine optimisation"]


def competitors(seo: int, aeo: int, geo: int) -> list[dict]:
    return [
        {
            "name": "semrush.com",
            "score": _scale(seo, 14),
            "source": "benchmark",
            "confidence_score": 0.88,
            "geo_visibility": _scale(geo, 19),
            "aeo_score": _scale(aeo, 16),
            "entity_strength": 84.0,
            "rank": 1,
        },
        {
            "name": "ahrefs.com",
            "score": _scale(seo, 8),
            "source": "benchmark",
            "confidence_score": 0.85,
            "geo_visibility": _scale(geo, 11),
            "aeo_score": _scale(aeo, 9),
            "entity_strength": 79.0,
            "rank": 2,
        },
    ]


RECOMMENDATIONS = [
    {
        "title": "Add FAQ and HowTo schema to the product pages",
        "summary": (
            "Nine pages answer a question directly in their copy but carry no "
            "structured data, so answer engines have to infer the answer."
        ),
        "category": "Technical",
        "priority": "high",
        "estimated_effort": "low",
        "expected_score_impact": 8,
    },
    {
        "title": "Publish comparison pages for the three terms you rank page two for",
        "summary": (
            "Search already sends impressions for comparison intent, and there is "
            "no page that answers it."
        ),
        "category": "Content",
        "priority": "high",
        "estimated_effort": "medium",
        "expected_score_impact": 7,
    },
    {
        "title": "Earn citations from two industry publications",
        "summary": (
            "Source authority trails both benchmarked competitors. Data-led "
            "stories are the cheapest route to a cited mention."
        ),
        "category": "Authority",
        "priority": "medium",
        "estimated_effort": "high",
        "expected_score_impact": 6,
    },
    {
        "title": "Fix the four readability findings on the pricing page",
        "summary": (
            "Long sentences and nested clauses reduce the chance of a clean "
            "extract when an engine quotes the page."
        ),
        "category": "Content",
        "priority": "medium",
        "estimated_effort": "low",
        "expected_score_impact": 4,
    },
    {
        "title": "Complete the organisation profile so the entity resolves cleanly",
        "summary": (
            "Name, address and identifiers are partially present, which leaves "
            "the organisation ambiguous to engines that disambiguate by entity."
        ),
        "category": "Entity",
        "priority": "low",
        "estimated_effort": "low",
        "expected_score_impact": 3,
    },
]


def main() -> int:
    assert_local_database()
    db = database.SessionLocal()
    try:
        project = db.query(models.Project).filter(models.Project.id == PROJECT_ID).first()
        if project is None:
            print(f"No project {PROJECT_ID}; nothing to seed.")
            return 1
        if EXPECTED_DOMAIN not in (project.domain_url or ""):
            print(
                f"Refusing to seed: project {PROJECT_ID} is {project.domain_url!r}, "
                f"which does not look like the local demo project ({EXPECTED_DOMAIN})."
            )
            return 1

        audits = (
            db.query(models.Audit)
            .filter(models.Audit.project_id == PROJECT_ID)
            .order_by(models.Audit.created_at.asc())
            .all()
        )
        if not audits:
            print("No audits on the demo project; run a scan first.")
            return 1

        for index, audit in enumerate(audits):
            step = PROGRESSION[min(index, len(PROGRESSION) - 1)]
            seo, aeo, geo = step["seo"], step["aeo"], step["geo"]
            overall = round((seo + aeo + geo) / 3)

            report = dict(audit.full_report or {})
            report["scores"] = {
                **(report.get("scores") or {}),
                "seo": seo,
                "aeo": aeo,
                "geo": geo,
                "overall": overall,
            }
            report["seo"] = {**(report.get("seo") or {}), **seo_block(seo)}
            report["aeo"] = {**(report.get("aeo") or {}), **aeo_block(aeo)}
            report["geo"] = {**(report.get("geo") or {}), **geo_block(geo)}
            report["entities"] = ENTITIES
            report["competitors"] = competitors(seo, aeo, geo)

            # Only the newest audit carries the full action plan, so the history
            # reads like a project that worked through its list.
            keep = len(RECOMMENDATIONS) if index == len(audits) - 1 else max(2, 5 - index)
            report["recommendations"] = {
                **(report.get("recommendations") or {}),
                "items": [
                    {**item, "id": f"demo-rec-{position + 1}"}
                    for position, item in enumerate(RECOMMENDATIONS[:keep])
                ],
            }
            metadata = dict(report.get("metadata") or {})
            metadata["demo_seed"] = "scripts/seed_demo_full_audit.py"
            report["metadata"] = metadata

            audit.full_report = report
            audit.seo_score = seo
            audit.aeo_score = aeo
            audit.geo_score = geo

        db.commit()
        print(f"Seeded {len(audits)} audits on project {PROJECT_ID} ({project.domain_url}).")
        for audit in audits:
            scores = (audit.full_report or {}).get("scores", {})
            print(
                f"  {audit.created_at.date()}  seo={scores.get('seo')} "
                f"aeo={scores.get('aeo')} geo={scores.get('geo')} "
                f"overall={scores.get('overall')} "
                f"recs={len((audit.full_report or {}).get('recommendations', {}).get('items', []))}"
            )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
