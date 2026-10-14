import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.entity.schema_gap_service import analyze_schema_gap


def test_schema_gap_service_generates_valid_product_snippet_from_empty_markup():
    result = analyze_schema_gap({"name": "Acme Widget", "type": "PRODUCT"}, existing_json_ld=None)

    assert result["recommended_schema_type"] == "Product"
    assert "name" not in result["missing_fields"]["required"]
    assert "description" in result["missing_fields"]["recommended"]
    assert result["validation"]["is_valid"] is True

    snippet = json.loads(result["json_ld_snippet"])
    assert snippet["@context"] == "https://schema.org"
    assert snippet["@type"] == "Product"
    assert snippet["name"] == "Acme Widget"


def test_schema_gap_service_detects_only_missing_local_business_fields():
    existing = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": "Acme Bakery",
        "address": {"@type": "PostalAddress", "streetAddress": "123 Main St"},
    }

    result = analyze_schema_gap(
        {"name": "Acme Bakery", "type": "LOCAL_BUSINESS"}, existing_json_ld=existing
    )

    assert result["recommended_schema_type"] == "LocalBusiness"
    assert result["missing_fields"]["required"] == ["telephone"]
    assert "openingHoursSpecification" in result["missing_fields"]["recommended"]

    snippet = json.loads(result["json_ld_snippet"])
    assert snippet["address"]["streetAddress"] == "123 Main St"
    assert "telephone" in snippet
    assert result["validation"]["is_valid"] is True
