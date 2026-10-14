import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"
os.environ["DATABASE_URL"] = "postgresql://user:password@localhost:5432/testdb"
os.environ["SSM_ENABLED"] = "0"

from services.advisor_service import ADVISOR_SCHEMA_VERSION, build_advisor_plan


def _sugg(action, impact, effort, *, grounded=True):
    s = {"action": action, "impact": impact, "effort": effort}
    if grounded:
        s["grounded_by_findings"] = ["seo.finding.1"]
        s["derived_from"] = ["seo-rec-01"]
    return s


def test_empty_input_returns_empty_plan():
    plan = build_advisor_plan([])
    assert plan["schema_version"] == ADVISOR_SCHEMA_VERSION
    assert plan["actions"] == []
    assert plan["strategic_summary"] is None
    assert plan["metadata"]["actions_count"] == 0


def test_ranks_high_impact_low_effort_first():
    plan = build_advisor_plan(
        [
            _sugg("low value, high effort", "low", "high"),
            _sugg("quick win", "high", "low"),
            _sugg("medium", "medium", "medium"),
        ]
    )
    actions = plan["actions"]
    assert [a["rank"] for a in actions] == [1, 2, 3]
    assert actions[0]["action"] == "quick win"  # highest ROI ranks first
    assert actions[-1]["action"] == "low value, high effort"


def test_ungrounded_suggestions_are_dropped_and_counted():
    plan = build_advisor_plan(
        [
            _sugg("grounded", "high", "low"),
            _sugg("ungrounded", "high", "low", grounded=False),
        ]
    )
    assert plan["metadata"]["actions_count"] == 1
    assert plan["metadata"]["dropped_ungrounded"] == 1
    assert plan["actions"][0]["action"] == "grounded"


def test_respects_max_actions_cap():
    suggestions = [_sugg(f"action {i}", "medium", "medium") for i in range(20)]
    plan = build_advisor_plan(suggestions, max_actions=5)
    assert plan["metadata"]["total_candidates"] == 20
    assert plan["metadata"]["actions_count"] == 5
    assert len(plan["actions"]) == 5


def test_is_deterministic_stable_order():
    suggestions = [
        _sugg("b action", "high", "low"),
        _sugg("a action", "high", "low"),  # same ROI + grounding -> tie-break on action text
    ]
    first = build_advisor_plan(suggestions)
    second = build_advisor_plan(list(reversed(suggestions)))
    assert [a["action"] for a in first["actions"]] == [a["action"] for a in second["actions"]]
    assert first["actions"][0]["action"] == "a action"  # alphabetical tie-break


def test_deterministic_only_has_no_strategic_summary():
    plan = build_advisor_plan([_sugg("x", "high", "low")])
    assert plan["strategic_summary"] is None
    assert plan["metadata"]["deterministic_only"] is True


def test_strategic_summary_none_when_no_actions():
    from services.advisor_service import generate_strategic_summary

    assert generate_strategic_summary(build_advisor_plan([])) is None


def test_strategic_summary_none_when_bedrock_unavailable(monkeypatch):
    import core.bedrock_text as bt
    from services.advisor_service import generate_strategic_summary

    monkeypatch.setattr(bt, "bedrock_available", lambda: False)
    plan = build_advisor_plan([_sugg("compress the hero image to webp", "high", "low")])
    assert generate_strategic_summary(plan) is None


def test_strategic_summary_calls_bedrock_with_grounding_system(monkeypatch):
    import core.bedrock_text as bt
    from services.advisor_service import generate_strategic_summary

    captured: dict = {}

    def _fake(system, user, **kwargs):
        captured["system"] = system
        captured["user"] = user
        captured["kwargs"] = kwargs
        return "  Tackle the quick win first, then the rest.  "

    monkeypatch.setattr(bt, "bedrock_available", lambda: True)
    monkeypatch.setattr(bt, "bedrock_generate_text", _fake)

    plan = build_advisor_plan([_sugg("compress the hero image to webp", "high", "low")])
    summary = generate_strategic_summary(plan, tier="smart")

    assert summary == "Tackle the quick win first, then the rest."
    assert captured["kwargs"]["use_case"] == "advisor_summary"
    assert "do NOT" in captured["system"]  # anti-hallucination grounding rule
    assert "compress the hero image to webp" in captured["user"]
