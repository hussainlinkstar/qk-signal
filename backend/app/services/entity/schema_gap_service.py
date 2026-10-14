from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

ENTITY_TYPE_TO_SCHEMA_TYPE = {
    "ORG": "Organization",
    "PERSON": "Person",
    "PRODUCT": "Product",
    "LOCAL_BUSINESS": "LocalBusiness",
    "LOCALBUSINESS": "LocalBusiness",
}

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

SCHEMA_ALLOWED_FIELDS: dict[str, set[str]] = {
    schema_type: set(
        requirements["required"] + requirements["recommended"] + ["@context", "@type", "@id"]
    )
    for schema_type, requirements in SCHEMA_REQUIREMENTS.items()
}

DEFAULT_VALUES: dict[str, dict[str, Any]] = {
    "Organization": {
        "url": "https://example.com",
        "logo": "https://example.com/logo.png",
        "sameAs": ["https://www.linkedin.com/company/your-brand"],
        "contactPoint": {
            "@type": "ContactPoint",
            "contactType": "customer support",
            "email": "support@example.com",
            "telephone": "+1-000-000-0000",
        },
    },
    "LocalBusiness": {
        "address": {
            "@type": "PostalAddress",
            "streetAddress": "123 Example St",
            "addressLocality": "City",
            "addressRegion": "State",
            "postalCode": "12345",
            "addressCountry": "US",
        },
        "telephone": "+1-000-000-0000",
        "openingHoursSpecification": [
            {
                "@type": "OpeningHoursSpecification",
                "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
                "opens": "09:00",
                "closes": "17:00",
            }
        ],
        "aggregateRating": {
            "@type": "AggregateRating",
            "ratingValue": "4.8",
            "reviewCount": "127",
        },
        "url": "https://example.com",
    },
    "Person": {
        "jobTitle": "Founder",
        "worksFor": {"@type": "Organization", "name": "Example Company"},
        "sameAs": ["https://www.linkedin.com/in/example"],
        "url": "https://example.com/about",
    },
    "Product": {
        "description": "A concise product description.",
        "offers": {
            "@type": "Offer",
            "priceCurrency": "USD",
            "price": "99.00",
            "availability": "https://schema.org/InStock",
        },
        "aggregateRating": {
            "@type": "AggregateRating",
            "ratingValue": "4.6",
            "reviewCount": "89",
        },
        "image": "https://example.com/product.jpg",
    },
    "Article": {
        "headline": "Article headline",
        "author": {"@type": "Person", "name": "Author Name"},
        "datePublished": "2026-01-01",
        "dateModified": "2026-01-01",
        "image": "https://example.com/article.jpg",
        "publisher": {"@type": "Organization", "name": "Publisher"},
        "mainEntityOfPage": "https://example.com/article",
    },
}


def analyze_schema_gap(
    detected_primary_entity: dict[str, Any], existing_json_ld: Any = None
) -> dict[str, Any]:
    recommended_type = _recommend_schema_type(detected_primary_entity)
    existing_node = _find_existing_node_for_type(existing_json_ld, recommended_type)

    required_fields = SCHEMA_REQUIREMENTS[recommended_type]["required"]
    recommended_fields = SCHEMA_REQUIREMENTS[recommended_type]["recommended"]

    missing_required = [
        field
        for field in required_fields
        if _is_missing(_resolve_field_value(field, detected_primary_entity, existing_node))
    ]
    missing_recommended = [
        field
        for field in recommended_fields
        if _is_missing(_resolve_field_value(field, detected_primary_entity, existing_node))
    ]

    snippet = _build_json_ld_snippet(recommended_type, detected_primary_entity, existing_node)
    validation = _validate_schema_org_snippet(snippet)
    if not validation["is_valid"]:
        raise ValueError(f"Generated JSON-LD snippet is invalid: {validation['errors']}")

    return {
        "recommended_schema_type": recommended_type,
        "missing_fields": {
            "required": missing_required,
            "recommended": missing_recommended,
        },
        "json_ld_snippet": json.dumps(snippet, indent=2),
        "validation": validation,
    }


def _resolve_field_value(
    field: str, detected_primary_entity: dict[str, Any], existing_node: dict[str, Any]
) -> Any:
    if field == "name" and detected_primary_entity.get("name"):
        return detected_primary_entity.get("name")
    return existing_node.get(field) if existing_node else None


def _recommend_schema_type(detected_primary_entity: dict[str, Any]) -> str:
    raw_type = str(detected_primary_entity.get("type") or "").upper()
    return ENTITY_TYPE_TO_SCHEMA_TYPE.get(raw_type, "Organization")


def _find_existing_node_for_type(existing_json_ld: Any, recommended_type: str) -> dict[str, Any]:
    nodes = _extract_json_ld_nodes(existing_json_ld)
    for node in nodes:
        node_types = _normalize_types(node.get("@type"))
        if recommended_type in node_types:
            return node

    if recommended_type == "Organization":
        for node in nodes:
            if "LocalBusiness" in _normalize_types(node.get("@type")):
                return node

    return {}


def _extract_json_ld_nodes(existing_json_ld: Any) -> list[dict[str, Any]]:
    if not existing_json_ld:
        return []

    parsed: Any = existing_json_ld
    if isinstance(existing_json_ld, str):
        try:
            parsed = json.loads(existing_json_ld)
        except json.JSONDecodeError:
            return []

    candidates = parsed if isinstance(parsed, list) else [parsed]
    nodes: list[dict[str, Any]] = []

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if "@graph" in candidate and isinstance(candidate["@graph"], list):
            nodes.extend([node for node in candidate["@graph"] if isinstance(node, dict)])
        else:
            nodes.append(candidate)

    return nodes


def _normalize_types(raw_type: Any) -> set[str]:
    if isinstance(raw_type, list):
        values = raw_type
    elif raw_type is None:
        values = []
    else:
        values = [raw_type]

    normalized = set()
    for value in values:
        text = str(value)
        if "/" in text:
            text = text.rsplit("/", 1)[-1]
        normalized.add(text)
    return normalized


def _build_json_ld_snippet(
    recommended_type: str,
    detected_primary_entity: dict[str, Any],
    existing_node: dict[str, Any],
) -> dict[str, Any]:
    snippet: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": recommended_type,
    }

    preferred_name = (
        detected_primary_entity.get("name")
        or existing_node.get("name")
        or f"Example {recommended_type}"
    )
    snippet["name"] = preferred_name

    defaults = deepcopy(DEFAULT_VALUES.get(recommended_type, {}))
    for field in (
        SCHEMA_REQUIREMENTS[recommended_type]["required"]
        + SCHEMA_REQUIREMENTS[recommended_type]["recommended"]
    ):
        if field == "name":
            continue
        if field in existing_node and not _is_missing(existing_node[field]):
            snippet[field] = existing_node[field]
            continue
        if field in defaults:
            snippet[field] = defaults[field]

    return snippet


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _validate_schema_org_snippet(snippet: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []

    if snippet.get("@context") != "https://schema.org":
        errors.append("@context must be 'https://schema.org'.")

    schema_type = snippet.get("@type")
    if schema_type not in SCHEMA_REQUIREMENTS:
        errors.append(f"Unsupported @type '{schema_type}'.")

    if schema_type in SCHEMA_REQUIREMENTS:
        required_fields = SCHEMA_REQUIREMENTS[schema_type]["required"]
        for field in required_fields:
            if _is_missing(snippet.get(field)):
                errors.append(f"Missing required field '{field}' for type '{schema_type}'.")

        allowed_fields = SCHEMA_ALLOWED_FIELDS[schema_type]
        for field in snippet.keys():
            if field not in allowed_fields:
                errors.append(f"Field '{field}' is not whitelisted for type '{schema_type}'.")

    return {"is_valid": len(errors) == 0, "errors": errors}
