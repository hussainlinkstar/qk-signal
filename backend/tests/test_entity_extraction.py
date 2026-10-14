import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest

from services.entity_extraction import extract_entity_candidates_from_url


class _FakeEntityService:
    async def analyze(self, url: str):
        assert url == "https://example.com"
        return {
            "primary_entity": {"name": "Acme", "type": "ORG", "confidence": 0.99},
            "entities": [
                {"name": "Acme", "type": "ORG", "confidence": 0.99},
                {"name": "Acme Widget", "type": "PRODUCT", "score": "0.88"},
                {"name": "Jane Doe", "type": "PERSON"},
            ],
        }


@pytest.mark.asyncio
async def test_extract_entity_candidates_from_url_returns_unique_typed_entities():
    results = await extract_entity_candidates_from_url(
        "https://example.com",
        entity_service=_FakeEntityService(),
    )

    assert results == [
        {"name": "Acme", "type": "Organization", "confidence": 0.99},
        {"name": "Acme Widget", "type": "Product", "confidence": 0.88},
        {"name": "Jane Doe", "type": "Person", "confidence": 0.7},
    ]
