from __future__ import annotations

import re
from typing import Any


class EntityGraphService:
    """Transforms extracted entity analysis output into graph node/edge records."""

    @staticmethod
    def _normalize_name(name: str) -> str:
        compact = re.sub(r"\s+", " ", name.strip().lower())
        return re.sub(r"[^a-z0-9 ]", "", compact)

    def stable_key(self, *, canonical_uri: str | None, name: str, entity_type: str) -> str:
        """Prefer canonical URI; otherwise derive from normalized type+name."""
        uri = (canonical_uri or "").strip()
        if uri:
            return f"uri:{uri.lower()}"
        normalized_name = self._normalize_name(name)
        return f"name:{entity_type.lower()}:{normalized_name}"

    @staticmethod
    def map_category(raw_type: str | None) -> str:
        normalized = str(raw_type or "").strip().upper()
        if normalized in {"PERSON"}:
            return "Person"
        if normalized in {"ORG", "ORGANIZATION", "LOCALBUSINESS"}:
            return "Organization"
        if normalized in {"PRODUCT"}:
            return "Product"
        return "Concept"

    @staticmethod
    def map_relation(raw_relation: str | None) -> str:
        normalized = str(raw_relation or "").strip().upper()
        if normalized == "MENTIONED_IN":
            return "MENTIONED_IN"
        return "RELATED_TO"

    def build_graph(self, analysis_result: dict[str, Any]) -> dict[str, Any]:
        page_url = str(analysis_result.get("url") or "")
        same_as_urls = analysis_result.get("same_as_urls") or []
        mention_relations = analysis_result.get("mention_relations") or []
        entities = analysis_result.get("entities") or []
        primary = analysis_result.get("primary_entity") or {}

        nodes_by_key: dict[str, dict[str, Any]] = {}
        edges_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}

        def upsert_node(
            name: str, entity_type: str, source_url: str, canonical_uri: str | None = None
        ):
            if not name.strip():
                return None
            key = self.stable_key(canonical_uri=canonical_uri, name=name, entity_type=entity_type)
            node = nodes_by_key.setdefault(
                key,
                {
                    "key": key,
                    "name": name.strip(),
                    "type": entity_type,
                    "category": self.map_category(entity_type),
                    "normalized_name": self._normalize_name(name),
                    "sourceURLs": set(),
                },
            )
            if source_url:
                node["sourceURLs"].add(source_url)
            return key

        for entity in entities:
            upsert_node(
                name=str(entity.get("name") or ""),
                entity_type=str(entity.get("type") or "Thing"),
                source_url=page_url,
            )

        primary_key = upsert_node(
            name=str(primary.get("name") or ""),
            entity_type=str(primary.get("type") or "ORG"),
            source_url=page_url,
        )

        for relation in mention_relations:
            source = relation.get("source")
            relation_type = self.map_relation(str(relation.get("relation") or ""))
            subject_key = upsert_node(
                name=str(relation.get("subject_name") or primary.get("name") or ""),
                entity_type=str(relation.get("subject_type") or primary.get("type") or "ORG"),
                source_url=str(relation.get("page_url") or page_url),
            )
            object_key = upsert_node(
                name=str(relation.get("object_name") or ""),
                entity_type=str(relation.get("object_type") or "Thing"),
                source_url=str(relation.get("page_url") or page_url),
            )
            if not subject_key or not object_key:
                continue
            edge_key = (subject_key, object_key, str(relation_type))
            edges_by_key[edge_key] = {
                "from": subject_key,
                "to": object_key,
                "relation": str(relation_type),
                "source": str(source or "unknown"),
                "page_url": str(relation.get("page_url") or page_url),
            }

        for same_as_url in same_as_urls:
            primary_name = str(primary.get("name") or "")
            primary_type = str(primary.get("type") or "ORG")
            if not primary_name:
                continue
            identity_node_key = upsert_node(
                name=same_as_url,
                entity_type="URI",
                source_url=page_url,
                canonical_uri=same_as_url,
            )
            if not primary_key or not identity_node_key:
                continue
            edge_key = (primary_key, identity_node_key, "RELATED_TO")
            edges_by_key[edge_key] = {
                "from": primary_key,
                "to": identity_node_key,
                "relation": "RELATED_TO",
                "source": "sameAs",
                "page_url": page_url,
            }
            upsert_node(name=primary_name, entity_type=primary_type, source_url=page_url)

        nodes = []
        for node in nodes_by_key.values():
            node["sourceURLs"] = sorted(node["sourceURLs"])
            nodes.append(node)

        categories = sorted({node["category"] for node in nodes})
        url_mentions = sorted(
            {
                source_url
                for node in nodes
                for source_url in node.get("sourceURLs", [])
                if isinstance(source_url, str) and source_url.strip()
            }
        )

        return {
            "url": page_url,
            "uniqueness": {
                "primary_key": "Entity.key",
                "strategy": "Use canonical URI when available; otherwise normalized type+name.",
                "recommended_indexes": [
                    "CREATE CONSTRAINT entity_key_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.key IS UNIQUE",
                    "CREATE INDEX entity_normalized_name_idx IF NOT EXISTS FOR (e:Entity) ON (e.normalized_name)",
                ],
            },
            "nodes": sorted(nodes, key=lambda item: item["key"]),
            "edges": sorted(
                edges_by_key.values(),
                key=lambda item: (item["from"], item["to"], item["relation"]),
            ),
            "categories": categories,
            "url_mentions": url_mentions,
        }
