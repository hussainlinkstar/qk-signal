"""Measure near-duplicate fixes in one Advisor plan (SIGV2-1118 follow-up).

The deterministic problem channel and the LLM both look at the same page, so
both can advise on the same problem, which would show the customer two cards
saying one thing on a page whose whole premise is a ranked plan. This harness
counts how often that actually happens and prints the pairs verbatim so a human
can judge how obvious the duplication looks.

Run it from the repository root:

    backend/.venv/bin/python scripts/measure_fix_plan_duplication.py

Each scenario is one audited page seen by BOTH channels: the deterministic
engine measures the page, and the LLM half returns its own recommendations plus
the findings that let those recommendations ground and reach the plan. No
network and no model calls: enrichment is a passthrough stub, which understates
how far the live enrichment rewords a fix and therefore makes the two cards look
MORE alike than in production. That is the conservative direction for counting
duplicates.

Limitation to keep in mind when reading the numbers: the repository holds no
recorded real audit payloads, so the LLM half of each scenario is written by
hand. It is modelled on what the expert prompts instruct the model to emit for a
page with these defects, but it is not a sample of production traffic.

The token-overlap screen below exists ONLY to shortlist pairs for human reading.
Shipped code never compares recommendation texts: identity is the deterministic
problem code, or nothing (see backend/problem_codes.py).
"""

from __future__ import annotations

import asyncio
import os
import re
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "backend"))

from app.services.advisor_view import attach_advisor_view  # noqa: E402
from audit_runner import perform_audit  # noqa: E402

# Shortlist threshold for the human-reading screen, not a product behaviour.
OVERLAP_SHORTLIST = 0.34

_STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "to",
    "of",
    "for",
    "on",
    "in",
    "it",
    "its",
    "so",
    "with",
    "that",
    "this",
    "page",
    "pages",
    "add",
    "set",
    "use",
    "your",
    "every",
    "each",
    "can",
    "cannot",
    "is",
    "are",
    "be",
    "as",
    "at",
    "by",
    "from",
    "into",
    "more",
    "than",
    "then",
    "when",
    "which",
    "while",
    "you",
    "they",
    "them",
    "their",
    "has",
    "have",
    "no",
    "not",
    "any",
    "all",
    "one",
    "single",
    "make",
    "ensure",
}


def _tokens(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 3 and w not in _STOP
    }


def _overlap(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


class _Scraper:
    def __init__(self, markdown: str, metadata: dict) -> None:
        self._markdown = markdown
        self._metadata = metadata

    async def get_page_content_and_screenshot(self, url: str) -> dict:
        metadata = dict(self._metadata)
        metadata.setdefault("url", url)
        return {
            "success_status": True,
            "markdown_content": self._markdown,
            "screenshot_base64": "c2NyZWVuc2hvdF9kYXRh",
            "metadata": metadata,
        }


class _Performance:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def get_performance_metrics(self, url: str) -> dict:
        return dict(self._payload)


class _Network:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def analyze_network_protocols(self, url: str) -> dict:
        return dict(self._payload)


class _LlmHalf:
    """The LLM side of the audit: recommendations plus grounding findings."""

    def __init__(self, analysis: dict) -> None:
        self._analysis = analysis

    async def generate_audit(self, *, provider: str, tier: str, **kwargs) -> dict:
        return {
            "analysis": dict(self._analysis),
            "model": "measurement-model",
            "provider": provider,
        }

    async def generate_suggestion_detail(self, *, suggestion: str, **kwargs) -> dict:
        return {
            "short_title": suggestion,
            "comprehensive_action": suggestion,
            "category": "technical",
        }

    async def extract_entities(
        self, *, provider: str, tier: str, content: str
    ) -> list[dict]:
        return [{"name": "Northwind", "confidence": 0.9}]


_BODY = (
    "Northwind Hotel sits on the canal ring in Amsterdam and has welcomed guests since 1931. "
    "Our rooms were renovated in 2024 and include air conditioning, blackout curtains and a desk. "
    "Breakfast is served between 7am and 10am in the garden room, and late checkout is available "
    "on request. We are a ten minute walk from Centraal Station and four tram stops from the "
    "museum quarter. Guests regularly ask about parking: the nearest garage is on Prins "
    "Hendrikkade and costs 45 euro per day. Pets are welcome in the garden wing for 20 euro per "
    "night. The hotel has 48 rooms across six floors, two meeting rooms and a bar that closes at "
    "midnight. We hold a Green Key certification and source breakfast produce from growers in "
    "North Holland. Cancellation is free up to 48 hours before arrival. " * 3
)

SCENARIOS: list[dict] = [
    {
        "label": "1. Homepage with no meta description and no H1, LLM saw the same gaps",
        "markdown": _BODY,
        "metadata": {"title": "Northwind Hotel Amsterdam", "description": ""},
        "performance": {"performance_score": 71, "metrics": {}},
        "network": {"https": True, "http2": True},
        "analysis": {
            "summary": "Strong content, weak head markup.",
            "recommendations": [
                "Write a unique meta description of 150 to 160 characters for the homepage.",
                "Introduce one H1 heading that names the hotel and its location.",
                "Publish a neighbourhood guide to capture long tail interest.",
            ],
            "seo_findings": [
                {
                    "description": "The homepage has no meta description, so search engines "
                    "generate their own snippet.",
                    "severity": "warning",
                    "category": "meta",
                },
                {
                    "description": "No H1 heading is present on the homepage.",
                    "severity": "warning",
                    "category": "headings",
                },
            ],
            "geo_findings": [],
            "aeo_findings": [],
            "seo_score": {"score": 68},
            "geo_score": {"score": 61},
            "aeo_score": {"score": 59},
        },
    },
    {
        "label": "2. Guide with no answer schema and dense prose, LLM saw both",
        "markdown": "# Canal district guide\n\n" + _BODY,
        "metadata": {
            "title": "A guide to the canal district",
            "description": "Everything to know about staying in the canal district of Amsterdam.",
            "canonical_url": "https://northwind.example/guide",
            "viewport": "width=device-width, initial-scale=1",
        },
        "performance": {"performance_score": 88, "metrics": {}},
        "network": {"https": True, "http2": True},
        "analysis": {
            "summary": "Useful guide, not structured for answer engines.",
            "recommendations": [
                "Mark up the question and answer block with FAQPage structured data.",
                "Shorten the longest sentences so the guide reads at a general level.",
                "Add an author byline with credentials to strengthen trust signals.",
            ],
            "seo_findings": [],
            "geo_findings": [],
            "aeo_findings": [
                {
                    "description": "The guide answers common questions but carries no FAQPage or "
                    "QAPage schema, so answer engines cannot extract it.",
                    "severity": "critical",
                    "category": "schema",
                },
                {
                    "description": "Sentence length and clause density push the reading level "
                    "above a general audience.",
                    "severity": "warning",
                    "category": "readability",
                },
            ],
            "seo_score": {"score": 79},
            "geo_score": {"score": 64},
            "aeo_score": {"score": 52},
        },
    },
    {
        "label": "3. Page served over http, LLM flagged the protocol too",
        "markdown": "# Meeting rooms\n\n" + _BODY,
        "metadata": {
            "title": "Meeting rooms in central Amsterdam",
            "description": "Two meeting rooms for up to twenty people, catering included.",
            "url": "http://northwind.example/meeting-rooms",
        },
        "performance": {"performance_score": 64, "metrics": {}},
        "network": {"https": False, "http2": False},
        "analysis": {
            "summary": "Content fine, delivery insecure.",
            "recommendations": [
                "Serve the meeting rooms page over HTTPS and redirect the HTTP version.",
                "Declare a canonical URL so the duplicate parameters stop competing.",
                "Collect three customer testimonials for the page.",
            ],
            "seo_findings": [
                {
                    "description": "The page is served over HTTP, which browsers mark as not "
                    "secure.",
                    "severity": "critical",
                    "category": "security",
                },
                {
                    "description": "No canonical URL is declared on the page.",
                    "severity": "warning",
                    "category": "indexing",
                },
            ],
            "geo_findings": [],
            "aeo_findings": [],
            "seo_score": {"score": 55},
            "geo_score": {"score": 58},
            "aeo_score": {"score": 57},
        },
    },
    {
        "label": "4. Clean page, LLM advice is strategic and does not overlap",
        "markdown": "# Sustainability at Northwind\n\n" + _BODY,
        "metadata": {
            "title": "Sustainability at Northwind Hotel",
            "description": "How Northwind Hotel reduces energy use and sources food locally.",
            "canonical_url": "https://northwind.example/sustainability",
            "viewport": "width=device-width, initial-scale=1",
            "schema_types": ["Organization", "FAQPage"],
        },
        "performance": {"performance_score": 95, "metrics": {}},
        "network": {"https": True, "http2": True, "http3": True},
        "analysis": {
            "summary": "Well built page.",
            "recommendations": [
                "Pitch the Green Key certification story to regional travel press.",
                "Compare the hotel against two named competitors on a dedicated page.",
            ],
            "seo_findings": [
                {
                    "description": "The page has few external authority signals pointing at it.",
                    "severity": "warning",
                    "category": "authority",
                }
            ],
            "geo_findings": [],
            "aeo_findings": [],
            "seo_score": {"score": 86},
            "geo_score": {"score": 81},
            "aeo_score": {"score": 83},
        },
    },
    {
        "label": "5. Thin landing page, LLM advice about depth only",
        "markdown": "# Rooms\n\nBook a room.\n",
        "metadata": {
            "title": "Rooms",
            "description": "Rooms at Northwind Hotel Amsterdam, renovated in 2024.",
            "canonical_url": "https://northwind.example/rooms",
            "viewport": "width=device-width, initial-scale=1",
        },
        "performance": {"performance_score": 90, "metrics": {}},
        "network": {"https": True, "http2": True},
        "analysis": {
            "summary": "Almost no content on the page.",
            "recommendations": [
                "Describe each room type with size, view, bed configuration and price band.",
                "Add internal links from the rooms page to the booking flow.",
            ],
            "seo_findings": [
                {
                    "description": "The rooms page carries only a handful of words, far below "
                    "what the query needs.",
                    "severity": "critical",
                    "category": "content",
                }
            ],
            "geo_findings": [],
            "aeo_findings": [],
            "seo_score": {"score": 48},
            "geo_score": {"score": 52},
            "aeo_score": {"score": 50},
        },
    },
    {
        "label": "6. Mobile-hostile page, LLM advice about viewport and speed",
        "markdown": "# Bar and garden\n\n" + _BODY,
        "metadata": {
            "title": "Bar and garden at Northwind Hotel",
            "description": "The Northwind bar and garden, open to guests and visitors.",
            "canonical_url": "https://northwind.example/bar",
        },
        "performance": {"performance_score": 38, "metrics": {}},
        "network": {"https": True, "http2": True},
        "analysis": {
            "summary": "Desktop only layout.",
            "recommendations": [
                "Add a responsive viewport meta tag so the page scales on phones.",
                "Compress the hero imagery to cut the largest contentful paint.",
            ],
            "seo_findings": [
                {
                    "description": "No mobile viewport meta tag is present, so phones render the "
                    "desktop layout.",
                    "severity": "critical",
                    "category": "mobile",
                },
                {
                    "description": "Hero imagery is uncompressed and delays the main content "
                    "paint.",
                    "severity": "warning",
                    "category": "performance",
                },
            ],
            "geo_findings": [],
            "aeo_findings": [],
            "seo_score": {"score": 60},
            "geo_score": {"score": 63},
            "aeo_score": {"score": 61},
        },
    },
]


def _refs(action: dict) -> set[str]:
    return set(action.get("grounded_by_findings") or []) | set(
        action.get("derived_from") or []
    )


async def main() -> None:
    plans = 0
    plans_shortlisted = 0
    shortlisted_pairs = 0
    coded_actions = 0
    llm_actions = 0
    llm_actions_with_penalty_ref = 0
    pairs_sharing_a_finding_ref = 0

    for scenario in SCENARIOS:
        report, _scores = await perform_audit(
            url=scenario["metadata"].get("url", "https://northwind.example/"),
            provider="google",
            tier="fast",
            user_plan="business",
            scraper_service=_Scraper(scenario["markdown"], scenario["metadata"]),
            performance_service=_Performance(scenario["performance"]),
            network_service=_Network(scenario["network"]),
            ai_client=_LlmHalf(scenario["analysis"]),
            hallucination_service=None,
        )
        actions = attach_advisor_view(report)["metadata"]["advisor"]["actions"]
        plans += 1

        coded = [a for a in actions if a.get("problem_code")]
        uncoded = [a for a in actions if not a.get("problem_code")]
        coded_actions += len(coded)
        llm_actions += len(uncoded)
        llm_actions_with_penalty_ref += sum(
            1 for a in uncoded if any(".penalty." in ref for ref in _refs(a))
        )

        print(f"\n{'=' * 78}\n{scenario['label']}")
        print(
            f"  plan size {len(actions)}: {len(coded)} coded, {len(uncoded)} LLM authored"
        )
        for action in actions:
            print(
                f"    [{action.get('problem_code') or '-':26}] {action['action'][:70]}"
            )
            print(f"       refs: {sorted(_refs(action))}")

        shortlisted_here = False
        for deterministic in coded:
            for llm_item in uncoded:
                score = _overlap(deterministic["action"], llm_item["action"])
                shared_findings = {
                    ref
                    for ref in (_refs(deterministic) & _refs(llm_item))
                    if ".finding." in ref
                }
                if shared_findings:
                    pairs_sharing_a_finding_ref += 1
                if score >= OVERLAP_SHORTLIST or shared_findings:
                    shortlisted_pairs += 1
                    shortlisted_here = True
                    print(
                        f"\n  SHORTLISTED PAIR (overlap {score:.2f}, "
                        f"shared finding refs {sorted(shared_findings)})"
                    )
                    print(
                        f"    deterministic [{deterministic['problem_code']}]: "
                        f"{deterministic['action']}"
                    )
                    print(f"    llm authored : {llm_item['action']}")
        if shortlisted_here:
            plans_shortlisted += 1

    print(f"\n{'=' * 78}\nSUMMARY")
    print(f"  plans examined                            : {plans}")
    print(f"  plan actions, deterministic               : {coded_actions}")
    print(f"  plan actions, LLM authored                : {llm_actions}")
    print(f"  plans with >=1 shortlisted pair           : {plans_shortlisted}")
    print(f"  shortlisted pairs (for human reading)     : {shortlisted_pairs}")
    print(
        f"  LLM actions carrying a '*.penalty.*' ref  : {llm_actions_with_penalty_ref}"
    )
    print(
        f"  pairs sharing a '*.finding.*' ref         : {pairs_sharing_a_finding_ref}"
    )
    print(
        "\n  Read the pairs above and judge them. The last two lines decide whether an\n"
        "  exact dedupe seam exists: a penalty reference on an LLM action would give one,\n"
        "  and a shared finding reference does NOT, because it is a keyword match made\n"
        "  upstream and it pairs unrelated fixes far more often than real duplicates."
    )


if __name__ == "__main__":
    asyncio.run(main())
