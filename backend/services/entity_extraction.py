from __future__ import annotations

import re
from dataclasses import dataclass

from services.entity_service import EntityService
from services.url_validation import normalize_and_validate_url

_MIN_ENTITY_LENGTH = 2
_SPACE_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True)
class EntityCandidate:
    name: str
    confidence: float
    source: str


def _sanitize_name(value: str) -> str:
    compact = _SPACE_PATTERN.sub(" ", str(value or "").strip())
    return compact.strip(" -_.,;:!?\t\n\r")


async def extract_entities_from_markdown(
    markdown_content: str | None, *, ai_client, provider: str, tier: str, max_entities: int = 12
) -> list[EntityCandidate]:
    if not markdown_content or not isinstance(markdown_content, str) or not ai_client:
        return []

    try:
        # Process a meaningful chunk to save tokens if content is very long
        content_sample = markdown_content[:15000]
        extracted = await ai_client.extract_entities(
            provider=provider, tier=tier, content=content_sample
        )

        results: list[EntityCandidate] = []
        for ent in extracted[:max_entities]:
            name = _sanitize_name(str(ent.get("name") or ""))
            if len(name) < _MIN_ENTITY_LENGTH:
                continue
            confidence = float(ent.get("confidence", 0.7))
            results.append(EntityCandidate(name=name, confidence=confidence, source="content"))
        return results
    except Exception:
        return []


def normalize_entities(
    candidates: list[EntityCandidate], *, min_confidence: float = 0.5
) -> list[str]:
    source_priority = {"request": 3, "ai": 2, "content": 1}
    merged: dict[str, tuple[str, float, int, int]] = {}
    for index, candidate in enumerate(candidates):
        name = _sanitize_name(candidate.name)
        if len(name) < _MIN_ENTITY_LENGTH:
            continue
        if candidate.confidence < min_confidence:
            continue

        key = name.casefold()
        priority = source_priority.get(candidate.source, 0)
        previous = merged.get(key)
        current = (name, candidate.confidence, priority, index)
        if previous is None:
            merged[key] = current
            continue

        _, previous_confidence, previous_priority, previous_index = previous
        if candidate.confidence > previous_confidence:
            merged[key] = current
        elif candidate.confidence == previous_confidence and priority > previous_priority:
            merged[key] = current
        elif (
            candidate.confidence == previous_confidence
            and priority == previous_priority
            and index < previous_index
        ):
            merged[key] = current

    ranked = sorted(merged.values(), key=lambda item: (-item[1], -item[2], item[3]))
    return [name for name, _, _, _ in ranked]


async def build_entity_list(
    *,
    ai_client=None,
    provider: str = "google",
    tier: str = "fast",
    ai_entities: list[str] | None,
    request_entities: list[str] | None,
    markdown_content: str | None,
    ai_min_entities: int = 2,
    min_confidence: float = 0.5,
) -> list[str]:
    candidates: list[EntityCandidate] = []

    ai_items = [str(item).strip() for item in (ai_entities or []) if str(item).strip()]
    for name in ai_items:
        candidates.append(EntityCandidate(name=name, confidence=0.95, source="ai"))

    request_items = [str(item).strip() for item in (request_entities or []) if str(item).strip()]
    for name in request_items:
        candidates.append(EntityCandidate(name=name, confidence=0.99, source="request"))

    if len(ai_items) < ai_min_entities and ai_client:
        candidates.extend(
            await extract_entities_from_markdown(
                markdown_content, ai_client=ai_client, provider=provider, tier=tier
            )
        )

    return normalize_entities(candidates, min_confidence=min_confidence)


def _normalize_entity_type(entity_type: str | None) -> str:
    normalized = str(entity_type or "").upper()
    if normalized == "ORG":
        return "Organization"
    if normalized == "PERSON":
        return "Person"
    if normalized == "PRODUCT":
        return "Product"
    return entity_type or "Entity"


def _normalize_entity_confidence(value: object, default: float = 0.7) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, parsed))


async def extract_entity_candidates_from_url(
    url: str,
    *,
    entity_service: EntityService | None = None,
    max_entities: int = 12,
) -> list[dict[str, str | float]]:
    normalized_url = normalize_and_validate_url(url)
    service = entity_service or EntityService()
    result = await service.analyze(normalized_url)

    raw_entities = result.get("entities", []) if isinstance(result, dict) else []
    primary_entity = result.get("primary_entity", {}) if isinstance(result, dict) else {}

    candidates: list[dict[str, str | float]] = []
    if isinstance(primary_entity, dict):
        primary_name = _sanitize_name(str(primary_entity.get("name") or ""))
        if primary_name:
            candidates.append(
                {
                    "name": primary_name,
                    "type": _normalize_entity_type(str(primary_entity.get("type") or "ORG")),
                    "confidence": _normalize_entity_confidence(
                        primary_entity.get("confidence"), default=1.0
                    ),
                }
            )

    if isinstance(raw_entities, list):
        for item in raw_entities:
            if not isinstance(item, dict):
                continue
            name = _sanitize_name(str(item.get("name") or ""))
            if not name:
                continue
            candidates.append(
                {
                    "name": name,
                    "type": _normalize_entity_type(str(item.get("type") or "Entity")),
                    "confidence": _normalize_entity_confidence(
                        item.get("confidence") or item.get("score"), default=0.7
                    ),
                }
            )

    deduped: list[dict[str, str | float]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate["name"].casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
        if len(deduped) >= max_entities:
            break

    return deduped
