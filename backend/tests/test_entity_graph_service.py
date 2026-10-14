import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.entity_graph_service import EntityGraphService


def test_entity_graph_deduplicates_nodes_by_stable_key():
    service = EntityGraphService()
    graph = service.build_graph(
        {
            "url": "https://example.com",
            "primary_entity": {"name": "Acme Bakery", "type": "ORG"},
            "entities": [
                {"name": "Acme Bakery", "type": "ORG"},
                {"name": "Acme Bakery", "type": "ORG"},
            ],
            "same_as_urls": [],
            "mention_relations": [],
        }
    )

    keys = [node["key"] for node in graph["nodes"]]
    assert keys.count("name:org:acme bakery") == 1
    assert graph["categories"] == ["Organization"]


def test_entity_graph_generates_related_and_mentioned_edges():
    service = EntityGraphService()
    graph = service.build_graph(
        {
            "url": "https://example.com",
            "primary_entity": {"name": "Acme Bakery", "type": "ORG"},
            "entities": [{"name": "Acme Bakery", "type": "ORG"}],
            "same_as_urls": ["https://www.instagram.com/acme-bakery"],
            "mention_relations": [
                {
                    "source": "text",
                    "relation": "MENTIONED_IN",
                    "subject_name": "Acme Bakery",
                    "subject_type": "ORG",
                    "object_name": "Sourdough Loaf",
                    "object_type": "PRODUCT",
                    "page_url": "https://example.com",
                }
            ],
        }
    )

    edge_types = {(edge["relation"], edge["source"]) for edge in graph["edges"]}
    assert ("MENTIONED_IN", "text") in edge_types
    assert ("RELATED_TO", "sameAs") in edge_types
    assert graph["url_mentions"] == ["https://example.com"]
