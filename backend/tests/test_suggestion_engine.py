import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.suggestions.suggestion_engine import generate_unified_suggestions


def test_generate_unified_suggestions_orders_by_roi_and_deduplicates() -> None:
    module_outputs = {
        "seo": {
            "recommendations": [
                {
                    "impact": "high",
                    "effort": "low",
                    "action": "Fix title tags",
                    "justification": "Improves click-through and ranking relevance.",
                },
                {
                    "impact": "medium",
                    "effort": "medium",
                    "action": "Add FAQ section",
                    "justification": "Supports richer answer snippets.",
                },
            ]
        },
        "geo": {
            "suggestions": [
                {
                    "impact": "high",
                    "effort": "low",
                    "action": "Fix title tags",
                    "justification": "Duplicate recommendation from another module.",
                }
            ]
        },
        "aeo": {
            "findings": [
                {
                    "impact": "high",
                    "effort": "medium",
                    "action": "Add citations to key claims",
                    "justification": "Raises trust for generated answers.",
                }
            ]
        },
    }

    result = generate_unified_suggestions(module_outputs)

    assert [item["action"] for item in result] == [
        "Fix title tags",
        "Add citations to key claims",
        "Add FAQ section",
    ]
    assert len(result) == 3


def test_generate_unified_suggestions_normalizes_missing_fields() -> None:
    module_outputs = [
        {
            "items": [
                {
                    "recommendation": "Compress images",
                    "reason": "Improves page speed and crawl efficiency.",
                    "impact": "HIGH",
                    "effort": "LOW",
                },
                {
                    "title": "Refine intro paragraph",
                    "why": "Makes answer extraction easier.",
                },
            ]
        }
    ]

    result = generate_unified_suggestions(module_outputs)

    assert result[0]["action"] == "Compress images"
    assert result[0]["impact"] == "high"
    assert result[0]["effort"] == "low"
    assert result[1]["impact"] == "medium"
    # SIGV2-1070: unrated effort stays null; the medium default was fabricated.
    assert result[1]["effort"] is None
    assert result[1]["justification"] == "Makes answer extraction easier."


def test_generate_unified_suggestions_derives_from_modules_when_recommendations_empty() -> None:
    module_outputs = {
        "analysis": {"recommendations": []},
        "performance": {
            "findings": [
                {
                    "impact": "high",
                    "effort": "low",
                    "action": "Reduce unused JavaScript",
                    "justification": "Improves interaction speed.",
                }
            ]
        },
        "network": {
            "suggestions": [
                {
                    "impact": "medium",
                    "effort": "low",
                    "action": "Enable HTTP/3",
                    "justification": "Improves transport efficiency.",
                }
            ]
        },
    }

    result = generate_unified_suggestions(module_outputs)

    assert [item["action"] for item in result] == [
        "Reduce unused JavaScript",
        "Enable HTTP/3",
    ]
