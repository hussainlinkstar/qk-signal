from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any

QUESTION_PREFIXES = (
    "who",
    "what",
    "when",
    "where",
    "why",
    "how",
    "is",
    "are",
    "can",
    "could",
    "should",
    "does",
    "do",
)
ANSWER_WORD_LIMIT = 60

SCHEMA_TEMPLATE_REGISTRY: dict[str, dict[str, Any]] = {
    "generic": {
        "required_types": ["FAQPage", "HowTo", "Product"],
        "high_impact_types": ["FAQPage", "HowTo", "Product"],
        "recommended_fields_by_type": {
            "FAQPage": ["mainEntity"],
            "HowTo": ["name", "step"],
            "Product": ["name", "description", "offers"],
        },
    },
    "software": {
        "required_types": ["FAQPage", "HowTo", "Product", "SoftwareApplication"],
        "high_impact_types": ["SoftwareApplication", "FAQPage", "HowTo"],
        "recommended_fields_by_type": {
            "FAQPage": ["mainEntity"],
            "HowTo": ["name", "step"],
            "Product": ["name", "description", "offers"],
            "SoftwareApplication": [
                "name",
                "description",
                "applicationCategory",
                "operatingSystem",
                "offers",
            ],
        },
    },
}


def calculate_schema_coverage(
    detected_types: set[str],
    required_types: set[str],
    high_impact_types: set[str],
) -> dict[str, Any]:
    if not required_types:
        return {
            "coverage_by_type": {},
            "coverage_percent": 100.0,
            "missing_high_impact_types": [],
        }

    coverage_by_type = {
        schema_type: 100.0 if schema_type in detected_types else 0.0
        for schema_type in sorted(required_types)
    }
    covered_count = sum(1 for schema_type in required_types if schema_type in detected_types)
    coverage_percent = round((covered_count / len(required_types)) * 100.0, 2)
    missing_high_impact_types = sorted(high_impact_types - detected_types)

    return {
        "coverage_by_type": coverage_by_type,
        "coverage_percent": coverage_percent,
        "missing_high_impact_types": missing_high_impact_types,
    }


class _StructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[dict[str, str]] = []
        self._capture_tag: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        if lower in {"h2", "h3", "p", "li", "blockquote", "td", "th"}:
            self._capture_tag = lower
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if self._capture_tag and lower == self._capture_tag:
            text = _normalize_text(" ".join(self._buffer))
            if text:
                self.blocks.append({"tag": self._capture_tag, "text": text})
            self._capture_tag = None
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture_tag:
            self._buffer.append(data)


class _JsonLdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.json_ld_blocks: list[str] = []
        self._capture_json_ld = False
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return

        attrs_map = {name.lower(): (value or "") for name, value in attrs}
        script_type = attrs_map.get("type", "").lower()
        if "application/ld+json" in script_type:
            self._capture_json_ld = True
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script" or not self._capture_json_ld:
            return

        block = _normalize_text(" ".join(self._buffer))
        if block:
            self.json_ld_blocks.append(block)

        self._capture_json_ld = False
        self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture_json_ld:
            self._buffer.append(data)


def _coerce_to_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _extract_json_ld_nodes(payload: Any) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item)
            return

        if not isinstance(value, dict):
            return

        if "@type" in value:
            nodes.append(value)

        graph = value.get("@graph")
        if graph is not None:
            walk(graph)

    walk(payload)
    return nodes


def _parse_json_ld_blocks(raw_html: str) -> list[dict[str, Any]]:
    parser = _JsonLdParser()
    parser.feed(raw_html or "")

    parsed_payloads: list[dict[str, Any]] = []
    for block in parser.json_ld_blocks:
        try:
            parsed_payloads.append(json.loads(block))
        except json.JSONDecodeError:
            continue

    return parsed_payloads


def analyze_json_ld_structure(
    raw_html: str,
    site_category: str | None = None,
    page_type: str | None = None,
) -> dict[str, Any]:
    """Analyze JSON-LD structured data in *raw_html*.

    When *page_type* is supplied the schema expectations are derived from
    ``page_type_detector.get_schema_expectations`` which knows that a
    Terms-of-Service page should NOT be flagged for missing ``FAQPage``
    schema.  This replaces the old behaviour that applied the same generic
    template to every page regardless of its purpose.
    """
    parsed_payloads = _parse_json_ld_blocks(raw_html)
    detected_types: set[str] = set()
    fields_by_type: dict[str, set[str]] = {}

    for payload in parsed_payloads:
        for node in _extract_json_ld_nodes(payload):
            node_types = [str(item) for item in _coerce_to_list(node.get("@type")) if item]
            if not node_types:
                continue

            node_fields = {key for key in node.keys() if key not in {"@context", "@type", "@id"}}

            for node_type in node_types:
                detected_types.add(node_type)
                fields_by_type.setdefault(node_type, set()).update(node_fields)

    # If page_type is provided, use page-type-aware schema expectations
    # instead of the legacy site-category-only registry.
    if page_type:
        try:
            from services.page_type_detector import get_schema_expectations

            expectations = get_schema_expectations(page_type)
            required_types = set(expectations.get("required_types", []))
            high_impact_types = set(expectations.get("high_impact_types", []))
            recommended_fields_by_type: dict[str, list[str]] = {}
        except ImportError:
            required_types = set()
            high_impact_types = set()
            recommended_fields_by_type = {}
    else:
        category = (site_category or "").strip().lower()
        template = SCHEMA_TEMPLATE_REGISTRY.get(category) or SCHEMA_TEMPLATE_REGISTRY.get(
            "generic", {}
        )
        required_types = set(template.get("required_types", []))
        high_impact_types = set(template.get("high_impact_types", []))
        recommended_fields_by_type = template.get("recommended_fields_by_type", {})

    missing_required_types = sorted(required_types - detected_types)

    missing_fields_by_type: dict[str, list[str]] = {}
    for schema_type, recommended_fields in recommended_fields_by_type.items():
        if schema_type not in detected_types:
            continue
        missing_fields = sorted(set(recommended_fields) - fields_by_type.get(schema_type, set()))
        if missing_fields:
            missing_fields_by_type[schema_type] = missing_fields

    high_impact_blockers: list[str] = []
    category_lower = (site_category or "").strip().lower()
    if category_lower == "software" and "SoftwareApplication" in missing_required_types:
        high_impact_blockers.append(
            "Missing SoftwareApplication schema is a high-impact AEO blocker for software sites."
        )

    coverage = calculate_schema_coverage(
        detected_types=detected_types,
        required_types=required_types,
        high_impact_types=high_impact_types,
    )

    return {
        "detected_schema_types": sorted(detected_types),
        "missing_required_types": missing_required_types,
        "missing_fields_by_type": missing_fields_by_type,
        "high_impact_blockers": high_impact_blockers,
        "coverage_by_type": coverage["coverage_by_type"],
        "coverage_percent": coverage["coverage_percent"],
        "missing_high_impact_types": coverage["missing_high_impact_types"],
    }


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _is_question_heading(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False

    if lowered.endswith("?"):
        return True

    return lowered.startswith(QUESTION_PREFIXES)


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def detect_extractable_answer_block(raw_html: str) -> dict[str, str | bool]:
    """Detects whether content contains an extractable Q&A block.

    Pattern:
    1) Question in H2/H3
    2) Direct answer paragraph in next <p> with fewer than 60 words
    3) Supporting details after that answer within the same section
    """
    parser = _StructureParser()
    parser.feed(raw_html or "")

    has_question_heading = False
    found_direct_answer_paragraph = False
    found_short_answer_paragraph = False
    found_supporting_details = False

    for index, block in enumerate(parser.blocks):
        if block["tag"] not in {"h2", "h3"}:
            continue
        if not _is_question_heading(block["text"]):
            continue

        has_question_heading = True

        next_index = index + 1
        if next_index >= len(parser.blocks):
            continue

        answer_block = parser.blocks[next_index]
        if answer_block["tag"] != "p":
            continue

        found_direct_answer_paragraph = True

        answer_word_count = _word_count(answer_block["text"])
        if answer_word_count >= ANSWER_WORD_LIMIT:
            continue

        found_short_answer_paragraph = True

        cursor = next_index + 1
        has_support = False
        while cursor < len(parser.blocks):
            candidate = parser.blocks[cursor]
            if candidate["tag"] in {"h2", "h3"}:
                break
            if candidate["text"]:
                has_support = True
                break
            cursor += 1

        if has_support:
            found_supporting_details = True
            return {"extractable": True, "reason": ""}

    if not has_question_heading:
        return {
            "extractable": False,
            "reason": "No H2/H3 question heading found.",
        }

    if not found_direct_answer_paragraph:
        return {
            "extractable": False,
            "reason": "Question heading must be immediately followed by an answer paragraph.",
        }

    if not found_short_answer_paragraph:
        return {
            "extractable": False,
            "reason": "Direct answer paragraph must be under 60 words.",
        }

    if not found_supporting_details:
        return {
            "extractable": False,
            "reason": "Direct answer must be followed by supporting details.",
        }

    return {
        "extractable": False,
        "reason": "Could not detect a complete question-answer-support pattern.",
    }
