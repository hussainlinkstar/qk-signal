import json
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse
from typing import Any

import httpx

from services.url_validation import normalize_and_validate_url

logger = logging.getLogger(__name__)

SCHEMA_REQUIREMENTS: dict[str, dict[str, list[str]]] = {
    "Organization": {
        "required": ["name", "url"],
        "recommended": ["logo", "sameAs", "contactPoint"],
    },
    "LocalBusiness": {
        "required": ["name", "address", "telephone"],
        "recommended": ["openingHoursSpecification", "aggregateRating", "url"],
    },
    "Person": {
        "required": ["name"],
        "recommended": ["jobTitle", "worksFor", "sameAs", "url"],
    },
    "Product": {
        "required": ["name"],
        "recommended": ["description", "offers", "aggregateRating", "image"],
    },
    "Article": {
        "required": ["headline", "author", "datePublished"],
        "recommended": ["dateModified", "image", "publisher", "mainEntityOfPage"],
    },
}

LOCAL_BUSINESS_HINTS = (
    "location",
    "visit us",
    "hours",
    "open now",
    "directions",
    "book appointment",
)


class _HtmlDataExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.meta: dict[str, str] = {}
        self.meta_properties: dict[str, str] = {}
        self.json_ld_raw: list[str] = []
        self._in_title = False
        self._in_json_ld = False
        self._buffer = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            content = attrs_dict.get("content")
            if content:
                if attrs_dict.get("name"):
                    self.meta[attrs_dict["name"].strip().lower()] = content.strip()
                if attrs_dict.get("property"):
                    self.meta_properties[attrs_dict["property"].strip().lower()] = content.strip()
        if tag == "script" and (attrs_dict.get("type") or "").lower() == "application/ld+json":
            self._in_json_ld = True
            self._buffer = ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag == "script" and self._in_json_ld:
            if self._buffer.strip():
                self.json_ld_raw.append(self._buffer.strip())
            self._in_json_ld = False
            self._buffer = ""

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._in_json_ld:
            self._buffer += data


@dataclass
class _EntityCandidate:
    name: str
    entity_type: str
    count: int
    source: str


class EntityService:
    def __init__(self, timeout_seconds: float = 20.0):
        self.timeout_seconds = timeout_seconds
        try:
            import spacy

            self._nlp = spacy.load("en_core_web_sm")
        except Exception:
            self._nlp = None

    async def analyze(self, url: str) -> dict[str, Any]:
        url = normalize_and_validate_url(url)
        html = await self._fetch_html(url)
        extractor = _HtmlDataExtractor()
        extractor.feed(html)
        plain_text = self._strip_html(html)
        schema_blocks = self._extract_schema_blocks(extractor.json_ld_raw)

        entity_result = self._extract_entities_and_primary(plain_text, url, extractor)
        relation_signals = self._collect_relation_signals(
            schema_blocks=schema_blocks,
            text_entities=entity_result.get("entities", []),
            page_url=url,
            primary_entity=entity_result.get("primary_entity", {}),
        )
        expected_type = self._infer_expected_schema_type(plain_text, extractor)
        comparison = self._compare_markup(expected_type, schema_blocks)
        missing_fields = self._build_missing_fields(schema_blocks, expected_type)

        return {
            "url": url,
            "primary_entity": entity_result["primary_entity"],
            "entities": entity_result["entities"],
            "same_as_urls": relation_signals["same_as_urls"],
            "mention_relations": relation_signals["mention_relations"],
            "expected_schema_type": expected_type,
            "detected_schema_blocks": schema_blocks,
            "comparison": comparison,
            "missing_fields_by_schema_type": missing_fields,
            "meta": {
                "title": extractor.title.strip() or None,
                "meta": extractor.meta,
                "meta_properties": extractor.meta_properties,
            },
        }

    async def _fetch_html(self, url: str) -> str:
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    def _strip_html(self, html: str) -> str:
        without_script = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
        without_style = re.sub(r"<style[\s\S]*?</style>", " ", without_script, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", without_style)
        text = unescape(text)
        return re.sub(r"\s+", " ", text).strip()

    def _extract_entities_and_primary(
        self, plain_text: str, page_url: str, extractor: _HtmlDataExtractor
    ) -> dict[str, Any]:
        candidates: list[_EntityCandidate] = []

        if self._nlp:
            doc = self._nlp(plain_text[:5000])
            named_entities = [
                (ent.text.strip(), ent.label_)
                for ent in doc.ents
                if ent.label_ in {"ORG", "PERSON", "PRODUCT"} and len(ent.text.strip()) > 2
            ]
            grouped_entities = Counter((name, label) for name, label in named_entities)
            for (name, label), count in grouped_entities.items():
                candidates.append(
                    _EntityCandidate(name=name, entity_type=label, count=count, source="spacy")
                )

        title_candidate = (
            extractor.meta.get("og:title")
            or extractor.meta_properties.get("og:title")
            or extractor.title
        ).strip()
        if title_candidate:
            title_name = re.split(r"[|\-:]", title_candidate)[0].strip()
            if title_name:
                candidates.append(
                    _EntityCandidate(
                        name=title_name, entity_type="ORG", count=2, source="title_heuristic"
                    )
                )

        domain_candidate = self._extract_domain_brand(page_url)
        if domain_candidate:
            candidates.append(
                _EntityCandidate(
                    name=domain_candidate, entity_type="ORG", count=1, source="domain_heuristic"
                )
            )

        if not candidates:
            fallback = plain_text[:80].strip() if plain_text else "Unknown"
            return {
                "primary_entity": {
                    "name": fallback,
                    "type": "ORG",
                    "confidence": 0.2,
                    "ambiguous": False,
                    "collisions": [],
                    "method": "text_fallback",
                },
                "entities": [],
            }

        merged = self._merge_candidates(candidates)
        ranked = self._rank_entities(merged, title_candidate=title_candidate, page_url=page_url)
        top = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None

        collisions: list[str] = []
        ambiguous = False
        if second and (top["score"] - second["score"]) <= 0.15:
            ambiguous = True
            collisions.append(second["name"])

        return {
            "primary_entity": {
                "name": top["name"],
                "type": top["type"],
                "confidence": round(top["score"], 3),
                "ambiguous": ambiguous,
                "collisions": collisions,
                "method": top["method"],
            },
            "entities": [
                {
                    "name": item["name"],
                    "type": item["type"],
                    "count": item["count"],
                    "confidence": round(item["score"], 3),
                    "method": item["method"],
                }
                for item in ranked
            ],
        }

    def _extract_domain_brand(self, page_url: str) -> str | None:
        parsed = urlparse(page_url)
        netloc = parsed.netloc.lower().split(":")[0]
        parts = [
            part
            for part in netloc.split(".")
            if part and part not in {"www", "com", "org", "net", "io", "co"}
        ]
        if not parts:
            return None
        return parts[0].replace("-", " ").title()

    def _merge_candidates(self, candidates: list[_EntityCandidate]) -> list[dict[str, Any]]:
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for candidate in candidates:
            key = (candidate.name.casefold(), candidate.entity_type)
            if key not in merged:
                merged[key] = {
                    "name": candidate.name,
                    "type": candidate.entity_type,
                    "count": 0,
                    "methods": set(),
                }
            merged[key]["count"] += candidate.count
            merged[key]["methods"].add(candidate.source)
        return list(merged.values())

    def _rank_entities(
        self, entities: list[dict[str, Any]], title_candidate: str, page_url: str
    ) -> list[dict[str, Any]]:
        domain_brand = (self._extract_domain_brand(page_url) or "").casefold()
        max_count = max(item["count"] for item in entities)
        for item in entities:
            score = item["count"] / max_count
            if title_candidate and item["name"].casefold() in title_candidate.casefold():
                score += 0.2
            if domain_brand and domain_brand == item["name"].casefold():
                score += 0.15
            item["score"] = min(score, 1.0)
            item["method"] = ",".join(sorted(item["methods"]))
            del item["methods"]
        return sorted(entities, key=lambda item: (item["score"], item["count"]), reverse=True)

    def _infer_expected_schema_type(self, plain_text: str, extractor: _HtmlDataExtractor) -> str:
        text = f"{extractor.title} {plain_text[:4000]}".lower()
        if any(hint in text for hint in ("product", "buy", "price", "add to cart")):
            return "Product"
        if any(hint in text for hint in ("blog", "article", "posted on", "reading time")):
            return "Article"
        if any(hint in text for hint in LOCAL_BUSINESS_HINTS):
            return "LocalBusiness"
        if any(hint in text for hint in ("team", "founder", "ceo", "about us", "company")):
            return "Organization"
        return "Organization"

    def _extract_schema_blocks(self, raw_blocks: list[str]) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for idx, raw in enumerate(raw_blocks, start=1):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug("Skipping invalid JSON-LD block %s", idx)
                continue

            nodes = parsed if isinstance(parsed, list) else [parsed]
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                types = node.get("@type")
                if isinstance(types, list):
                    type_values = [str(item) for item in types]
                elif types is None:
                    type_values = []
                else:
                    type_values = [str(types)]
                blocks.append(
                    {
                        "source": "json-ld",
                        "types": type_values,
                        "name": node.get("name"),
                        "fields": sorted([key for key in node.keys() if not key.startswith("@")]),
                        "raw": node,
                    }
                )
        return blocks

    def _compare_markup(
        self, expected_type: str, schema_blocks: list[dict[str, Any]]
    ) -> dict[str, Any]:
        present_types = {t for block in schema_blocks for t in block.get("types", [])}
        return {
            "expected_type": expected_type,
            "present_types": sorted(present_types),
            "expected_type_present": expected_type in present_types,
        }

    def _build_missing_fields(
        self, schema_blocks: list[dict[str, Any]], expected_type: str
    ) -> dict[str, dict[str, list[str]]]:
        grouped_fields: dict[str, set[str]] = defaultdict(set)
        for block in schema_blocks:
            for schema_type in block.get("types", []):
                grouped_fields[schema_type].update(block.get("fields", []))

        result: dict[str, dict[str, list[str]]] = {}
        types_to_evaluate = set(grouped_fields.keys())
        if expected_type in SCHEMA_REQUIREMENTS:
            types_to_evaluate.add(expected_type)

        for schema_type in sorted(types_to_evaluate):
            if schema_type not in SCHEMA_REQUIREMENTS:
                continue
            present = grouped_fields.get(schema_type, set())
            required = SCHEMA_REQUIREMENTS[schema_type]["required"]
            recommended = SCHEMA_REQUIREMENTS[schema_type]["recommended"]
            result[schema_type] = {
                "missing_required": [field for field in required if field not in present],
                "missing_recommended": [field for field in recommended if field not in present],
            }

        return result

    def _collect_relation_signals(
        self,
        schema_blocks: list[dict[str, Any]],
        text_entities: list[dict[str, Any]],
        page_url: str,
        primary_entity: dict[str, Any],
    ) -> dict[str, list[Any]]:
        same_as_urls: set[str] = set()
        mention_relations: list[dict[str, Any]] = []
        seen_mentions: set[tuple[str, str, str]] = set()

        for block in schema_blocks:
            raw = block.get("raw") or {}
            block_name = str(raw.get("name") or block.get("name") or "").strip()
            block_type = block.get("types", ["Thing"])[0] if block.get("types") else "Thing"

            for same_as_url in self._extract_same_as_urls(raw.get("sameAs")):
                same_as_urls.add(same_as_url)

            for mention in self._extract_json_ld_mentions(raw):
                mention_name = mention.get("name", "").strip()
                mention_type = mention.get("type", "Thing")
                if not mention_name:
                    continue
                mention_key = (mention_name.casefold(), mention_type.casefold(), "json-ld")
                if mention_key in seen_mentions:
                    continue
                seen_mentions.add(mention_key)
                mention_relations.append(
                    {
                        "source": "json-ld",
                        "relation": "RELATED_TO",
                        "subject_name": block_name,
                        "subject_type": block_type,
                        "object_name": mention_name,
                        "object_type": mention_type,
                        "page_url": page_url,
                    }
                )

        primary_name = str(primary_entity.get("name") or "").strip()
        primary_type = str(primary_entity.get("type") or "ORG")
        for entity in text_entities:
            entity_name = str(entity.get("name") or "").strip()
            entity_type = str(entity.get("type") or "Thing")
            if not entity_name:
                continue
            mention_key = (entity_name.casefold(), entity_type.casefold(), "text")
            if mention_key in seen_mentions:
                continue
            seen_mentions.add(mention_key)
            mention_relations.append(
                {
                    "source": "text",
                    "relation": "MENTIONED_IN",
                    "subject_name": primary_name,
                    "subject_type": primary_type,
                    "object_name": entity_name,
                    "object_type": entity_type,
                    "page_url": page_url,
                }
            )

        return {
            "same_as_urls": sorted(same_as_urls),
            "mention_relations": mention_relations,
        }

    def _extract_same_as_urls(self, raw_same_as: Any) -> list[str]:
        if raw_same_as is None:
            return []
        values = raw_same_as if isinstance(raw_same_as, list) else [raw_same_as]
        urls: list[str] = []
        for value in values:
            if isinstance(value, str):
                candidate = value.strip()
                if candidate.startswith(("http://", "https://")):
                    urls.append(candidate)
        return urls

    def _extract_json_ld_mentions(self, node: dict[str, Any]) -> list[dict[str, str]]:
        mentions: list[dict[str, str]] = []
        for key in ("mentions", "about", "mainEntity", "itemListElement"):
            raw_values = node.get(key)
            if raw_values is None:
                continue
            items = raw_values if isinstance(raw_values, list) else [raw_values]
            for item in items:
                if isinstance(item, dict):
                    name = str(item.get("name") or item.get("headline") or "").strip()
                    item_type = item.get("@type")
                    if isinstance(item_type, list):
                        resolved_type = str(item_type[0]) if item_type else "Thing"
                    elif item_type:
                        resolved_type = str(item_type)
                    else:
                        resolved_type = "Thing"
                    if name:
                        mentions.append({"name": name, "type": resolved_type})
                elif isinstance(item, str):
                    name = item.strip()
                    if name:
                        mentions.append({"name": name, "type": "Thing"})
        return mentions
