from services.knowledge_service import KnowledgeService


def test_knowledge_service_loading():
    """Verify that the knowledge service correctly loads the standard files."""
    service = KnowledgeService()

    # Check that cache is not empty
    assert len(service._cache) >= 3

    # Check specific categories
    assert "seo" in service._cache
    assert "geo" in service._cache
    assert "aeo" in service._cache

    # Check content fragments
    seo_content = service.get_domain_context("seo")
    assert "Core Web Vitals" in seo_content
    assert "E-E-A-T" in seo_content

    geo_content = service.get_domain_context("geo")
    assert "LocalBusiness" in geo_content
    assert "NAP Consistency" in geo_content

    aeo_content = service.get_domain_context("aeo")
    assert "Citation Hook" in aeo_content
    assert "Answer-First Content Architecture" in aeo_content


def test_knowledge_service_combined_context():
    """Verify that get_domain_context returns all when no category is provided."""
    service = KnowledgeService()
    combined = service.get_domain_context()

    assert "SEO Industry Standards" in combined
    assert "GEO Standards" in combined
    assert "AEO Standards" in combined


def test_knowledge_service_invalid_category():
    """Verify that invalid categories return empty string."""
    service = KnowledgeService()
    assert service.get_domain_context("non_existent") == ""
