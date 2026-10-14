import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest

from services.entity_service import EntityService


@pytest.mark.asyncio
async def test_entity_service_extracts_schema_and_missing_fields(monkeypatch):
    html = """
    <html>
      <head>
        <title>Acme Bakery | Fresh Bread</title>
        <meta property='og:title' content='Acme Bakery'>
        <script type='application/ld+json'>
        {
          "@context": "https://schema.org",
          "@type": "LocalBusiness",
          "name": "Acme Bakery",
          "sameAs": [
            "https://www.facebook.com/acme-bakery",
            "https://www.instagram.com/acme-bakery"
          ],
          "mentions": {
            "@type": "Product",
            "name": "Sourdough Loaf"
          },
          "address": {
            "@type": "PostalAddress",
            "streetAddress": "123 Main St"
          }
        }
        </script>
      </head>
      <body>
        <h1>Acme Bakery</h1>
        <p>Visit us for fresh bread. Open now.</p>
      </body>
    </html>
    """

    service = EntityService()

    async def fake_fetch(_url: str) -> str:
        return html

    monkeypatch.setattr(service, "_fetch_html", fake_fetch)

    result = await service.analyze("https://example.com")

    assert result["primary_entity"]["name"] == "Acme Bakery"
    assert result["primary_entity"]["type"] == "ORG"
    assert 0 <= result["primary_entity"]["confidence"] <= 1
    assert isinstance(result["entities"], list)
    assert result["entities"][0]["name"] == "Acme Bakery"
    assert result["same_as_urls"] == [
        "https://www.facebook.com/acme-bakery",
        "https://www.instagram.com/acme-bakery",
    ]
    assert any(
        relation["source"] == "json-ld"
        and relation["relation"] == "RELATED_TO"
        and relation["object_name"] == "Sourdough Loaf"
        for relation in result["mention_relations"]
    )
    assert result["expected_schema_type"] == "LocalBusiness"
    assert result["comparison"]["expected_type_present"] is True
    assert result["missing_fields_by_schema_type"]["LocalBusiness"]["missing_required"] == [
        "telephone"
    ]


def test_entity_service_detects_ambiguous_brand_collisions():
    class FakeEnt:
        def __init__(self, text: str, label: str):
            self.text = text
            self.label_ = label

    class FakeDoc:
        def __init__(self):
            self.ents = [
                FakeEnt("Apple", "ORG"),
                FakeEnt("Apple", "ORG"),
                FakeEnt("Apple", "PRODUCT"),
                FakeEnt("Apple TV", "PRODUCT"),
                FakeEnt("Apple TV", "PRODUCT"),
            ]

    class FakeNLP:
        def __call__(self, _text: str):
            return FakeDoc()

    service = EntityService()
    service._nlp = FakeNLP()

    result = service._extract_entities_and_primary(
        plain_text="Apple launched a new Apple TV device.",
        page_url="https://apple.com/tv",
        extractor=type("E", (), {"meta": {}, "meta_properties": {}, "title": "Apple TV"})(),
    )

    assert result["primary_entity"]["name"] in {"Apple", "Apple TV"}
    assert result["primary_entity"]["ambiguous"] is True
    assert result["primary_entity"]["collisions"]
    assert all(0 <= entity["confidence"] <= 1 for entity in result["entities"])
