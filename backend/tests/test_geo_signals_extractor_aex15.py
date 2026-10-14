"""AEX-15: Dynamic Location / Service Label Detection — comprehensive tests.

Covers:
  - International address format detection (UK, EU, RO, DE, FR, ES)
  - Expanded proximity keyword detection (multilingual)
  - Service-area pattern detection
  - Industry-specific location vocabulary
  - Schema.org location property detection
  - Integration with score_utils GEO scoring sub-components
  - Backward compatibility (no regression for US-format detection)
"""

from __future__ import annotations


from services.geo_signals_extractor import (
    EXPANDED_PROXIMITY_TERMS,
    GeoSignalResult,
    geo_signals_extractor_service,
)
from score_utils import DeterministicScoringEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_engine = DeterministicScoringEngine


def _extract(
    content: str = "", schema: dict | None = None, meta: dict | None = None
) -> GeoSignalResult:
    return geo_signals_extractor_service.extract(
        content=content,
        schema_analysis=schema,
        scrape_metadata=meta,
    )


def _geo_score(
    content: str = "", schema: dict | None = None, meta: dict | None = None, brand_name: str = ""
):
    return _engine.calculate_geo_score(
        schema_analysis=schema,
        scrape_metadata=meta,
        content=content,
        brand_name=brand_name,
    )


# ===================================================================
# 1. International address format detection
# ===================================================================


class TestUKPostcodeDetection:
    def test_standard_uk_postcode(self):
        result = _extract("Our office is at 10 Downing Street, SW1A 2AA, London")
        assert "uk_postcode" in result.address_formats_detected
        assert result.has_international_signals

    def test_short_uk_postcode(self):
        result = _extract("Visit us at M1 1AA Manchester")
        assert "uk_postcode" in result.address_formats_detected

    def test_longer_uk_postcode(self):
        result = _extract("Located at EC2R 8AH in the City of London")
        assert "uk_postcode" in result.address_formats_detected

    def test_no_postcode_in_plain_text(self):
        result = _extract("There is nothing geographic about this text at all")
        assert "uk_postcode" not in result.address_formats_detected


class TestEUPostalCodeDetection:
    def test_german_postal_code(self):
        result = _extract("Unser Büro befindet sich in 10115 Berlin")
        assert "eu_postal" in result.address_formats_detected

    def test_french_postal_code(self):
        result = _extract("Notre bureau se trouve au 75001 Paris")
        assert "eu_postal" in result.address_formats_detected

    def test_austrian_postal_code(self):
        result = _extract("Wir sind in 1010 Wien zu finden")
        assert "eu_postal" in result.address_formats_detected

    def test_spanish_postal_code(self):
        result = _extract("Nuestra oficina está en 28001 Madrid")
        assert "es_postal" in result.address_formats_detected


class TestRomanianPostalCode:
    def test_romanian_postal_code(self):
        result = _extract("Sediul nostru este la 010011 Bucuresti")
        assert "ro_postal" in result.address_formats_detected

    def test_cluj_postal_code(self):
        result = _extract("Vizitati-ne la 400001 Cluj-Napoca")
        assert "ro_postal" in result.address_formats_detected


class TestGermanPrefixPostalCode:
    def test_de_prefix(self):
        result = _extract("Adresse: DE-10115 Berlin, Germany")
        assert "de_prefix" in result.address_formats_detected

    def test_at_prefix(self):
        result = _extract("Standort: AT-1010 Wien")
        assert "de_prefix" in result.address_formats_detected


class TestFrenchCedex:
    def test_cedex_address(self):
        result = _extract("75008 PARIS CEDEX 08")
        assert "fr_cedex" in result.address_formats_detected


# ===================================================================
# 2. Expanded proximity / local-intent terms
# ===================================================================


class TestExpandedProximityTerms:
    def test_original_terms_still_detected(self):
        for term in [
            "near me",
            "nearby",
            "local",
            "closest",
            "in the area",
            "neighborhood",
            "within miles",
        ]:
            result = _extract(f"Find services {term}")
            prox_signals = [s for s in result.signals if s.category == "proximity"]
            assert any(s.label == term for s in prox_signals), f"'{term}' not detected"

    def test_new_english_terms(self):
        new_terms = [
            "directions to",
            "miles from",
            "open now",
            "hours of operation",
            "located in",
            "zip code",
            "service area",
        ]
        for term in new_terms:
            result = _extract(f"Check {term} our office")
            prox_signals = [s for s in result.signals if s.category == "proximity"]
            assert any(s.label == term for s in prox_signals), f"'{term}' not detected"

    def test_german_proximity_terms(self):
        result = _extract("Finden Sie uns in der nähe")
        prox_signals = [s for s in result.signals if s.category == "proximity"]
        assert any("nähe" in s.label for s in prox_signals)

    def test_french_proximity_terms(self):
        result = _extract("Trouvez-nous à proximité")
        prox_signals = [s for s in result.signals if s.category == "proximity"]
        assert any("proximité" in s.label for s in prox_signals)

    def test_spanish_proximity_terms(self):
        result = _extract("Encuéntranos cerca de tu ubicación")
        prox_signals = [s for s in result.signals if s.category == "proximity"]
        assert any("cerca de" in s.label for s in prox_signals)

    def test_romanian_proximity_terms(self):
        result = _extract("Ne găsiți în apropiere de centru")
        prox_signals = [s for s in result.signals if s.category == "proximity"]
        assert any("în apropiere" in s.label for s in prox_signals)

    def test_expanded_terms_count_exceeds_original(self):
        assert len(EXPANDED_PROXIMITY_TERMS) > 7


# ===================================================================
# 3. Service-area detection patterns
# ===================================================================


class TestServiceAreaDetection:
    def test_serving_the_greater_area(self):
        result = _extract("Serving the greater Chicago area since 1985")
        assert result.service_area_detected

    def test_proudly_serving(self):
        result = _extract("Proudly serving Portland and surrounding areas")
        assert result.service_area_detected

    def test_available_in(self):
        result = _extract("Available in Manchester for same-day delivery")
        assert result.service_area_detected

    def test_throughout_region(self):
        result = _extract("We operate throughout the Dallas metro")
        # "throughout the Dallas" should match
        assert result.service_area_detected

    def test_surrounding_areas(self):
        result = _extract("Denver and surrounding areas are covered by our team")
        assert result.service_area_detected

    def test_no_service_area_in_generic_text(self):
        result = _extract("This is a regular paragraph with no location mentions at all")
        assert not result.service_area_detected


# ===================================================================
# 4. Industry-specific location vocabulary
# ===================================================================


class TestIndustryLocationVocabulary:
    def test_healthcare_clinic(self):
        result = _extract("Visit our clinic for a comprehensive checkup")
        assert "healthcare" in result.industry_labels_detected

    def test_healthcare_hospital(self):
        result = _extract("The hospital is located downtown")
        assert "healthcare" in result.industry_labels_detected

    def test_retail_store(self):
        result = _extract("Visit our store at the mall")
        assert "retail" in result.industry_labels_detected

    def test_retail_showroom(self):
        result = _extract("Come see the new models in our showroom")
        assert "retail" in result.industry_labels_detected

    def test_hospitality_hotel(self):
        result = _extract("Book your stay at our hotel")
        assert "hospitality" in result.industry_labels_detected

    def test_education_campus(self):
        result = _extract("The main campus is on University Avenue")
        assert "education" in result.industry_labels_detected

    def test_food_restaurant(self):
        result = _extract("Our restaurant serves Italian cuisine")
        assert "food" in result.industry_labels_detected

    def test_automotive_dealership(self):
        result = _extract("Browse our inventory at the dealership")
        assert "automotive" in result.industry_labels_detected

    def test_fitness_gym(self):
        result = _extract("Join our gym today")
        assert "fitness" in result.industry_labels_detected

    def test_professional_office(self):
        result = _extract("Schedule a meeting at our office")
        assert "professional" in result.industry_labels_detected

    def test_multiple_industries_detected(self):
        result = _extract("The hotel has a restaurant and a gym on the ground floor")
        assert len(result.industry_labels_detected) >= 2

    def test_no_industry_in_abstract_text(self):
        result = _extract("The algorithm processes data efficiently using advanced techniques")
        assert len(result.industry_labels_detected) == 0


# ===================================================================
# 5. Schema.org location properties
# ===================================================================


class TestSchemaLocationProperties:
    def test_postal_address_in_schema(self):
        schema = {"detected_schema_types": ["LocalBusiness"], "raw": "PostalAddress"}
        result = _extract(schema=schema)
        assert "PostalAddress" in result.schema_location_properties

    def test_area_served_in_schema(self):
        schema = {"detected_schema_types": ["LocalBusiness"], "areaServed": "Chicago"}
        result = _extract(schema=schema)
        assert "areaServed" in result.schema_location_properties

    def test_geo_coordinates_in_schema(self):
        schema = {
            "detected_schema_types": ["GeoCoordinates"],
            "latitude": "41.8781",
            "longitude": "-87.6298",
        }
        result = _extract(schema=schema)
        assert "latitude" in result.schema_location_properties
        assert "longitude" in result.schema_location_properties

    def test_schema_signals_have_highest_weight(self):
        schema = {"detected_schema_types": ["LocalBusiness"], "raw": "PostalAddress"}
        result = _extract(schema=schema)
        schema_signals = [s for s in result.signals if s.category == "schema"]
        assert all(s.quality_weight == 1.0 for s in schema_signals)

    def test_no_schema_properties_when_empty(self):
        result = _extract(schema={})
        assert len(result.schema_location_properties) == 0


# ===================================================================
# 6. GeoSignalResult utility methods
# ===================================================================


class TestGeoSignalResultUtils:
    def test_signal_count(self):
        result = _extract("Visit our clinic at SW1A 2AA London, serving the greater London area")
        assert result.signal_count > 0
        assert result.signal_count == len(result.signals)

    def test_bonus_points_for_international(self):
        result = _extract("Our office is at 10115 Berlin, visit our clinic")
        pts = result.bonus_points()
        assert pts > 0

    def test_bonus_points_capped_at_35(self):
        result = _extract(
            "Office at SW1A 2AA London. Also 75001 Paris. Clinic in 10115 Berlin. "
            "Serving the greater London area. Visit our hospital, store, and hotel."
        )
        assert result.bonus_points() <= 35.0

    def test_empty_content_gives_zero_bonus(self):
        result = _extract("")
        assert result.bonus_points() == 0.0


# ===================================================================
# 7. Integration — score_utils GEO scoring
# ===================================================================


class TestGeoScoringIntegration:
    def test_schema_boosts_entity_clarity(self):
        """LocalBusiness schema should contribute to entity clarity score."""
        result = _geo_score(
            content="Welcome to our London headquarters at SW1A 2AA",
            schema={"detected_schema_types": ["LocalBusiness"]},
        )
        entity = result.components.get("entity_clarity", 0)
        assert entity > 0, "LocalBusiness schema should boost entity clarity"

    def test_rich_content_boosts_citability(self):
        """Rich content with definitions should boost content citability."""
        content = (
            "<h1>Machine Learning Guide</h1>"
            "<h2>What is ML?</h2>"
            "<p>Machine Learning is defined as a subset of AI. It refers to algorithms that learn from data.</p>"
            + " ".join(["word"] * 400)
        )
        result = _geo_score(content=content)
        citability = result.components.get("content_citability", 0)
        assert citability > 0, "Rich content should boost content citability"

    def test_authority_signals_boost_source_authority(self):
        """Content with author and authoritative links should boost source authority."""
        content = (
            "<p>Written by Dr. Jane Smith. Published: 2024-03-15.</p>"
            '<a href="https://scholar.google.com/paper">Research</a>'
            '<a href="https://www.gov.uk/guidance">Government guidance</a>'
        )
        result = _geo_score(content=content, meta={"author": "Dr. Jane Smith"})
        authority = result.components.get("source_authority", 0)
        assert authority > 0, "Authority signals should boost source authority"

    def test_metadata_contains_extracted_geo_signals(self):
        result = _geo_score(
            content="Visit our clinic at SW1A 2AA, serving the greater London area",
            schema={"detected_schema_types": ["LocalBusiness"]},
        )
        meta = result.metadata
        assert "extracted_geo_signals" in meta
        signals_meta = meta["extracted_geo_signals"]
        assert signals_meta["signal_count"] > 0
        assert "uk_postcode" in signals_meta["address_formats"]
        assert signals_meta["service_area_detected"] is True
        assert "healthcare" in signals_meta["industry_labels"]

    def test_multiple_schemas_accumulate_entity_clarity(self):
        """Multiple AI-relevant schemas should accumulate entity clarity points."""
        schema = {"detected_schema_types": ["Organization", "Article", "FAQPage"]}
        result = _geo_score(content="Some text", schema=schema)
        entity = result.components.get("entity_clarity", 0)
        assert entity > 0, "Multiple schemas should give entity clarity points"

    def test_empty_content_low_citability(self):
        """Page with zero content signals gets low citability score."""
        result = _geo_score(content="Algorithm optimization and data processing framework")
        citability = result.components.get("content_citability", 0)
        # Short content with no headings/definitions should be very low
        assert citability <= 10

    def test_structured_data_weighted_highest(self):
        """Schema.org locations get highest quality weight in extractor."""
        result = _extract(
            content="Our clinic in London",
            schema={
                "detected_schema_types": ["LocalBusiness"],
                "raw": "PostalAddress streetAddress",
            },
        )
        schema_signals = [s for s in result.signals if s.category == "schema"]
        content_signals = [s for s in result.signals if s.category in ("industry", "proximity")]
        if schema_signals and content_signals:
            assert max(s.quality_weight for s in schema_signals) > max(
                s.quality_weight for s in content_signals
            )


# ===================================================================
# 8. Backward compatibility
# ===================================================================


class TestBackwardCompatibility:
    def test_calculate_geo_score_with_no_content(self):
        """Empty content should not crash."""
        result = _geo_score(content="")
        assert result.total_score >= 0

    def test_calculate_geo_score_with_none_schema(self):
        result = _geo_score(content="Some text", schema=None)
        assert result.total_score >= 0

    def test_v31_component_keys_present(self):
        """V3.1 component keys should be present in result."""
        result = _geo_score(content="Some content here with enough words to analyze.")
        for key in ("content_citability", "source_authority", "entity_clarity", "brand_citation"):
            assert key in result.components, f"V3.1 key '{key}' missing from components"
