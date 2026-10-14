"""SIGV2-1118: a dismissed fix must stay dismissed after the next audit.

The product promise is explicit on the fixes page: "Dismissing a fix tells
Advisor not to recommend it again, it is suppressed from future audits, not just
hidden from this list." Keying a dismissal on the recommendation's action text
could not deliver that, because the text is written by an LLM on every audit and
its wording drifts, so the stored key stopped matching and the fix came back.

These tests pin the four behaviours that fix has to have, and the one it must
never acquire:

1. Same deterministic problem, LLM-reworded title between two audits: the
   dismissal survives.
2. A legacy row, keyed on the raw text digest and with no ``action_label``,
   still suppresses. Those rows cannot be re-keyed by any backfill, so the
   legacy path is permanent.
3. A fix that was never dismissed is never suppressed, including when its text
   closely resembles a dismissed one. This is the false-positive guard: a
   reappearing fix is visible and merely annoying, while hiding advice the
   customer never dismissed is invisible and withholds what they pay for, so
   identity must only ever fail toward showing the fix.
4. A report persisted before ``problem_code`` existed still validates and still
   renders its Advisor plan.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from app.models.audit import AuditResult, RecommendationItem
from app.services.advisor_plan_snapshot_service import compute_plan_delta
from app.services.advisor_view import attach_advisor_view
from app.services.learnings_service import (
    compute_action_fingerprint,
    decision_key,
    dismissed_fingerprints,
    is_suppressed,
    record_decision,
)
from app.services.suggestions.problem_code_suggestions import build_problem_code_suggestions
from app.services.suggestions.suggestion_engine import generate_unified_suggestions
from audit_runner import _to_canonical_suggestions
from database import Base
from problem_codes import PROBLEM_CODE_KEY_PREFIX, problem_code_key

# The same underlying problem, as two different audits worded it. Only the
# deterministic code is identical.
AUDIT_1_TEXT = "Add a unique meta description to the page."
AUDIT_2_TEXT = (
    "Write a compelling, unique meta description for this page so search engines "
    "can show a useful snippet in results."
)
PROBLEM_CODE = "missing_meta_description"


def _report(items: list[dict]) -> dict:
    return {"recommendations": {"items": items}}


def _item(action: str, *, problem_code: str | None = None, ref: str = "seo.finding.1") -> dict:
    item = {
        "action": action,
        "impact": "high",
        "estimated_effort": "low",
        "grounded_by_findings": [ref],
    }
    if problem_code is not None:
        item["problem_code"] = problem_code
    return item


def _plan_actions(report: dict) -> list[str]:
    return [action["action"] for action in report["metadata"]["advisor"]["actions"]]


# --------------------------------------------------------------------------- #
# 1. The defect: a reworded title must not resurrect a dismissed fix.
# --------------------------------------------------------------------------- #


def test_dismissal_survives_llm_rewording_between_audits():
    """The regression this ticket exists for.

    Fails on the previous implementation: the dismissal was stored as the sha256
    of the first audit's wording, the second audit's wording hashes differently,
    so the fix reappeared.
    """
    stored_key = decision_key(AUDIT_1_TEXT, PROBLEM_CODE)
    assert stored_key == f"{PROBLEM_CODE_KEY_PREFIX}{PROBLEM_CODE}"

    first_audit = attach_advisor_view(
        _report([_item(AUDIT_1_TEXT, problem_code=PROBLEM_CODE)]),
        dismissed={stored_key},
    )
    assert _plan_actions(first_audit) == []

    second_audit = attach_advisor_view(
        _report([_item(AUDIT_2_TEXT, problem_code=PROBLEM_CODE)]),
        dismissed={stored_key},
    )
    assert _plan_actions(second_audit) == [], "a reworded title resurrected a dismissed fix"


def test_rewording_alone_would_not_match_the_legacy_key():
    """Why the code is needed at all: the text digests genuinely differ."""
    assert compute_action_fingerprint(AUDIT_1_TEXT) != compute_action_fingerprint(AUDIT_2_TEXT)
    assert problem_code_key(PROBLEM_CODE) == f"{PROBLEM_CODE_KEY_PREFIX}{PROBLEM_CODE}"


# --------------------------------------------------------------------------- #
# 2. Legacy rows keep working, permanently.
# --------------------------------------------------------------------------- #


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _project(db) -> models.Project:
    user = models.User(email="owner@example.com", hashed_password="x", role="user")
    db.add(user)
    db.commit()
    db.refresh(user)
    workspace = models.Workspace(name="WS", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    project = models.Project(
        workspace_id=workspace.id,
        name="Project A",
        icp_roles=[],
        competitors_json=[],
        priority_pulse_tags=[],
        sme_profiles=[],
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def test_legacy_text_hash_row_with_null_label_still_suppresses():
    """A pre-``problem_code`` row keeps suppressing its fix.

    These rows were written as sha256(action text) and the oldest carry no
    ``action_label``, so nothing can re-key them. Reads must therefore match the
    legacy digest forever, including for a recommendation that now also carries
    a deterministic code.
    """
    db = _session()
    project = _project(db)

    legacy = models.RecommendationDecision(
        project_id=project.id,
        action_fingerprint=compute_action_fingerprint(AUDIT_1_TEXT),
        action_label=None,
        decision="dismissed",
        note=None,
        decided_by=None,
    )
    db.add(legacy)
    db.commit()

    dismissed = dismissed_fingerprints(db, project.id)
    assert dismissed == {compute_action_fingerprint(AUDIT_1_TEXT)}

    report = attach_advisor_view(
        _report([_item(AUDIT_1_TEXT, problem_code=PROBLEM_CODE)]),
        dismissed=dismissed,
    )
    assert _plan_actions(report) == [], "a legacy dismissal stopped suppressing its fix"
    db.close()


def test_recorded_decision_round_trips_through_the_code_key():
    """Writing with a code and reading back suppresses a differently worded fix."""
    db = _session()
    project = _project(db)

    record_decision(
        db,
        project_id=project.id,
        action_fingerprint=decision_key(AUDIT_1_TEXT, PROBLEM_CODE),
        decision="dismissed",
        decided_by=None,
        action_label=AUDIT_1_TEXT,
    )
    db.commit()

    dismissed = dismissed_fingerprints(db, project.id)
    assert dismissed == {f"{PROBLEM_CODE_KEY_PREFIX}{PROBLEM_CODE}"}

    report = attach_advisor_view(
        _report([_item(AUDIT_2_TEXT, problem_code=PROBLEM_CODE)]),
        dismissed=dismissed,
    )
    assert _plan_actions(report) == []
    db.close()


# --------------------------------------------------------------------------- #
# 3. False-positive guard: the most important test in the set.
# --------------------------------------------------------------------------- #


def test_never_dismissed_fix_is_never_suppressed():
    """Nothing but an exact key match may hide a fix."""
    dismissed = {decision_key(AUDIT_1_TEXT, PROBLEM_CODE)}

    # A different deterministic problem, in near-identical words.
    other_code_similar_text = _item(
        "Add a unique meta description to the page template.",
        problem_code="missing_page_title",
    )
    # Text that closely resembles the dismissed one, with no code at all.
    uncoded_similar_text = _item("Add a unique meta description to the pages.")
    # The dismissed WORDING, but a different underlying problem. A decision
    # stored under a code suppresses that code and nothing else: identity is
    # the failing check, so reusing its sentence elsewhere cannot hide the
    # other fix.
    same_text_other_code = _item(AUDIT_1_TEXT, problem_code="missing_h1")

    report = attach_advisor_view(
        _report([other_code_similar_text, uncoded_similar_text, same_text_other_code]),
        dismissed=dismissed,
    )
    actions = _plan_actions(report)
    assert sorted(actions) == sorted(
        [
            "Add a unique meta description to the page template.",
            "Add a unique meta description to the pages.",
            AUDIT_1_TEXT,
        ]
    )


def test_unknown_and_malformed_keys_suppress_nothing():
    """A key outside the registry can never hide a recommendation."""
    action = _item(AUDIT_1_TEXT, problem_code=PROBLEM_CODE)
    for junk in (
        "problem:not_a_registered_code",
        "problem:",
        "problem:MISSING_META_DESCRIPTION; DROP TABLE",
        "",
        "deadbeef",
    ):
        report = attach_advisor_view(_report([action]), dismissed={junk})
        assert _plan_actions(report) == [AUDIT_1_TEXT], junk


def test_is_suppressed_requires_an_exact_key_match():
    dismissed = {f"{PROBLEM_CODE_KEY_PREFIX}{PROBLEM_CODE}"}
    assert is_suppressed(dismissed, AUDIT_2_TEXT, PROBLEM_CODE)
    assert not is_suppressed(dismissed, AUDIT_2_TEXT, "missing_h1")
    assert not is_suppressed(dismissed, AUDIT_2_TEXT, None)
    assert not is_suppressed(dismissed, AUDIT_2_TEXT, "not_a_registered_code")
    assert not is_suppressed(None, AUDIT_1_TEXT, PROBLEM_CODE)
    assert not is_suppressed(set(), AUDIT_1_TEXT, PROBLEM_CODE)


def test_an_unknown_code_falls_back_to_text_identity():
    """Degrading to the text key may under-suppress, never over-suppress."""
    assert decision_key(AUDIT_1_TEXT, "not_a_registered_code") == compute_action_fingerprint(
        AUDIT_1_TEXT
    )
    assert decision_key(AUDIT_1_TEXT, None) == compute_action_fingerprint(AUDIT_1_TEXT)


# --------------------------------------------------------------------------- #
# 4. Reports persisted before the field existed.
# --------------------------------------------------------------------------- #


def test_persisted_report_without_problem_code_validates_and_renders():
    """An old stored ``full_report`` must keep validating and rendering.

    ``RecommendationItem`` is ``extra="forbid"`` and ``strict=True``, so the new
    field has to be optional with a default. The fixture is the committed
    canonical payload sample with a recommendation item in the exact shape the
    pipeline persisted before this change: no ``problem_code`` key at all.
    """
    sample_path = Path(__file__).resolve().parents[2] / "contracts"
    payload = json.loads(
        (sample_path / "canonical_audit_payload.sample.json").read_text(encoding="utf-8")
    )
    legacy_item = {
        "id": "rec.add-faqpage-schema",
        "priority": 1,
        "category": "technical",
        "title": "Add FAQPage schema",
        "summary": "Mark up the existing Q and A block.",
        "action": "Add FAQPage schema to the pricing page.",
        "rationale": "The page answers questions with no schema.",
        "derived_from": ["seo.finding.1"],
        "grounded_by_findings": ["seo.finding.1"],
        "expected_score_impact": {"seo": 4, "geo": None, "aeo": 6, "overall": 3},
        "cross_score_leverage": ["seo", "aeo"],
        "estimated_effort": "low",
        "owner": "engineering",
        "dependencies": [],
        "confidence": "high",
        "source_type": "deterministic_plus_ai_packaging",
        "client_safe": True,
        "requires_human_review": False,
    }
    assert "problem_code" not in legacy_item
    payload["recommendations"]["items"] = [legacy_item]

    validated = AuditResult.model_validate_json(json.dumps(payload))
    item = validated.recommendations.items[0]
    assert item.problem_code is None

    rendered = attach_advisor_view(validated.model_dump(mode="json"))
    assert _plan_actions(rendered) == ["Add FAQPage schema to the pricing page."]


def test_recommendation_item_accepts_and_rejects_problem_code_values():
    assert RecommendationItem(id="r1", title="t", action="a").problem_code is None
    coded = RecommendationItem(id="r1", title="t", action="a", problem_code=PROBLEM_CODE)
    assert coded.problem_code == PROBLEM_CODE


# --------------------------------------------------------------------------- #
# The channel that gives a recommendation its code in the first place.
# --------------------------------------------------------------------------- #


def test_only_coded_deterministic_penalties_become_candidates():
    """Codes may only come from deterministic checks."""
    deterministic_scores = {
        "seo_breakdown": {
            "penalties": [
                {"reason": "Missing meta description", "impact": -15, "code": PROBLEM_CODE},
                {"reason": "Scraping failed, content-dependent SEO checks skipped", "impact": 0},
                {"reason": "AI-detected issue: thin pricing copy", "impact": -4},
                {"reason": "Title too short", "impact": -5, "code": "title_too_short"},
            ]
        },
        "aeo_breakdown": {
            "penalties": [
                # Same check penalising a second dimension: one fix, not two.
                {"reason": "Missing meta description", "impact": -15, "code": PROBLEM_CODE},
                {"reason": "Unregistered future check", "impact": -9, "code": "not_in_registry"},
            ]
        },
    }

    candidates = build_problem_code_suggestions(deterministic_scores)
    codes = [candidate["problem_code"] for candidate in candidates]
    assert codes == [PROBLEM_CODE, "title_too_short"]

    first = candidates[0]
    assert first["impact"] == "high"
    assert first["effort"] is None
    assert first["derived_from"] == [f"seo.penalty.{PROBLEM_CODE}"]
    assert "Missing meta description" in first["justification"]
    # Impact is read off the engine's own point deduction, never guessed.
    assert candidates[1]["impact"] == "low"


def test_a_penalty_reference_never_travels_without_its_problem_code():
    """SIGV2-1193 reads this reference as a fallback join key. It is dormant.

    The consolidated fix list joins the audit's findings to the action plan on
    ``problem_code``, and falls back to decoding the code out of a
    ``{dimension}.penalty.{code}`` grounding reference for an entry that has no
    code of its own. This test states why that fallback can never fire today:
    the one function that emits the reference emits the code in the same dict,
    and the reverse case is pinned by
    ``test_llm_items_never_receive_a_penalty_reference`` below.

    If this starts failing, the fallback has become live and the frontend's
    ``problemCodeFromGroundingRefs`` is doing real work rather than standing by.
    """
    candidates = build_problem_code_suggestions(
        {
            "seo_breakdown": {
                "penalties": [
                    {"reason": "Missing meta description", "impact": -15, "code": PROBLEM_CODE},
                    {"reason": "Title too short", "impact": -5, "code": "title_too_short"},
                ]
            }
        }
    )

    assert candidates
    for candidate in candidates:
        code = candidate["problem_code"]
        references = list(candidate["grounded_by_findings"]) + list(candidate["derived_from"])
        penalty_references = [ref for ref in references if ".penalty." in ref]
        assert penalty_references, "the deterministic channel must name the penalty it read"
        assert code, "a penalty reference without its code would make the fallback join live"
        assert all(ref.endswith(f".penalty.{code}") for ref in penalty_references)


def test_build_problem_code_suggestions_is_defensive():
    assert build_problem_code_suggestions(None) == []
    assert build_problem_code_suggestions({}) == []
    assert build_problem_code_suggestions({"seo_breakdown": {"penalties": "nope"}}) == []
    assert build_problem_code_suggestions({"seo_breakdown": {"penalties": [None, 7]}}) == []


def test_unified_suggestions_dedupe_on_code_and_keep_it():
    module_outputs = {
        "deterministic_problems": {
            "suggestions": [
                {
                    "action": AUDIT_1_TEXT,
                    "impact": "high",
                    "effort": None,
                    "problem_code": PROBLEM_CODE,
                    "grounded_by_findings": [f"seo.penalty.{PROBLEM_CODE}"],
                    "derived_from": [f"seo.penalty.{PROBLEM_CODE}"],
                },
                {
                    "action": AUDIT_2_TEXT,
                    "impact": "medium",
                    "effort": "low",
                    "problem_code": PROBLEM_CODE,
                },
            ]
        },
        "analysis": {"suggestions": [{"action": "Publish a comparison page", "impact": "medium"}]},
    }

    unified = generate_unified_suggestions(module_outputs)
    coded = [s for s in unified if s["problem_code"] == PROBLEM_CODE]
    assert len(coded) == 1, "two phrasings of one deterministic problem produced two fixes"
    assert coded[0]["grounded_by_findings"] == [f"seo.penalty.{PROBLEM_CODE}"]
    uncoded = [s for s in unified if s["problem_code"] is None]
    assert [s["action"] for s in uncoded] == ["Publish a comparison page"]


def test_enrichment_rewrites_the_text_but_cannot_change_the_code():
    """The pipeline step that causes the drift must not touch identity."""

    class _RewritingClient:
        async def generate_suggestion_detail(self, **_kwargs):
            return {
                "short_title": "Craft a snippet-ready meta description",
                "comprehensive_action": AUDIT_2_TEXT,
                "category": "Technical",
                "estimated_effort": "low",
                "owner": "engineering",
                "confidence": "high",
                "affected_scores": ["seo"],
            }

    canonical, _transcript = asyncio.run(
        _to_canonical_suggestions(
            unified_suggestions=[
                {
                    "action": AUDIT_1_TEXT,
                    "impact": "high",
                    "effort": None,
                    "justification": "A deterministic check failed.",
                    "problem_code": PROBLEM_CODE,
                    "grounded_by_findings": [f"seo.penalty.{PROBLEM_CODE}"],
                    "derived_from": [f"seo.penalty.{PROBLEM_CODE}"],
                }
            ],
            ai_client=_RewritingClient(),
            provider="google",
            tier="fast",
            market="us",
            language="en",
        )
    )

    assert len(canonical) == 1
    enriched = canonical[0]
    assert enriched["action"] == AUDIT_2_TEXT, "the enrichment step should have rewritten the text"
    assert enriched["problem_code"] == PROBLEM_CODE
    assert enriched["derived_from"] == [f"seo.penalty.{PROBLEM_CODE}"]


# --------------------------------------------------------------------------- #
# Why the two channels cannot be deduped exactly (measured, then pinned).
#
# The deterministic channel and the LLM both read the same page, so both can
# advise on the same problem and the plan can show two cards for one fix. The
# only exact dedupe seam that would fix that is a shared evidence reference:
# drop the deterministic candidate when an LLM item is already grounded to the
# SAME penalty. These tests pin why that seam does not exist, so the premise of
# that decision fails loudly if the grounding model ever changes.
#
# Measured over the scenarios in scripts/measure_fix_plan_duplication.py:
# 0 of 5 LLM-authored plan actions carried a penalty reference, while 8 pairs
# shared a keyword-matched finding reference of which only 2 were really the
# same fix. Deduping on the finding reference would therefore delete the wrong
# card in 6 of 8 cases, which is the invisible failure this design refuses.
# --------------------------------------------------------------------------- #


def test_llm_items_never_receive_a_penalty_reference():
    """Keyword grounding can only ever produce finding references.

    If this starts failing because something grounds an LLM recommendation to a
    penalty, an exact dedupe seam has appeared and the duplicate-card decision
    should be revisited.
    """
    from audit_runner import _ground_suggestions_to_findings

    llm_suggestion = {
        "action": "Serve the meeting rooms page over HTTPS and redirect the HTTP version.",
        "problem_code": None,
    }
    deterministic_suggestion = {
        "action": "Serve the page over HTTPS.",
        "problem_code": "no_https",
        "grounded_by_findings": ["seo.penalty.no_https"],
        "derived_from": ["seo.penalty.no_https"],
    }
    findings = {
        "seo": [
            {
                "description": "The page is served over HTTP, which browsers mark as not secure.",
                "severity": "critical",
                "category": "security",
            }
        ]
    }

    grounded = _ground_suggestions_to_findings([llm_suggestion, deterministic_suggestion], findings)

    llm_refs = list(grounded[0].get("grounded_by_findings") or []) + list(
        grounded[0].get("derived_from") or []
    )
    assert llm_refs, "the LLM item should still ground to the finding"
    assert all(".penalty." not in ref for ref in llm_refs)

    # The deterministic candidate keeps the penalty reference that identifies it,
    # with the keyword-matched finding merged in rather than overwriting it.
    deterministic_refs = grounded[1]["grounded_by_findings"]
    assert "seo.penalty.no_https" in deterministic_refs
    assert any(".finding." in ref for ref in deterministic_refs)


# --------------------------------------------------------------------------- #
# Progress and suppression must answer the same question the same way.
# --------------------------------------------------------------------------- #


def test_plan_delta_reads_a_reworded_coded_action_as_carried():
    previous = {
        "actions": [{"action": AUDIT_1_TEXT, "impact": "high", "problem_code": PROBLEM_CODE}]
    }
    current = {
        "actions": [{"action": AUDIT_2_TEXT, "impact": "high", "problem_code": PROBLEM_CODE}]
    }

    delta = compute_plan_delta(previous, current)
    assert [view["problem_code"] for view in delta["actions_carried"]] == [PROBLEM_CODE]
    assert delta["actions_added"] == []
    assert delta["actions_resolved"] == []


def test_plan_delta_still_uses_text_identity_without_a_code():
    previous = {"actions": [{"action": "Publish a comparison page", "impact": "medium"}]}
    current = {"actions": [{"action": "Publish a comparison page", "impact": "medium"}]}

    delta = compute_plan_delta(previous, current)
    assert [view["fingerprint"] for view in delta["actions_carried"]] == [
        compute_action_fingerprint("Publish a comparison page")
    ]
