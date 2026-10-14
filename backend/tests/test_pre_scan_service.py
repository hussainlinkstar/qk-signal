import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services import pre_scan_service


@pytest.fixture
def snapshot_payload():
    return {
        "url": "https://example.com",
        "title": "Acme",
        "meta_description": "Acme SaaS platform",
        "headings": ["Acme Platform"],
        "body_excerpt": "Acme offers SaaS workflow automation in Romania.",
        "html_lang": "en",
        "og_locale": "en_US",
    }


def test_analyze_url_returns_cached_result_before_ai_lookup(
    monkeypatch: pytest.MonkeyPatch,
    snapshot_payload: dict,
) -> None:
    monkeypatch.setattr(pre_scan_service, "fetch_url_snapshot", lambda _url: dict(snapshot_payload))
    monkeypatch.setattr(
        pre_scan_service.semantic_cache_service,
        "get_json",
        lambda **_kwargs: {
            "response": {
                "language": "en",
                "market_region": "Romania",
                "category": "SaaS",
                "primary_entities": ["Acme"],
                "source": "bedrock_pre_scan",
            }
        },
    )

    result = pre_scan_service.analyze_target("website", "https://example.com", None)

    assert result["language"] == "en"
    assert result["category"] == "SaaS"
    assert result["source"] == "semantic_cache"


def test_analyze_url_stores_fresh_result_in_semantic_cache(
    monkeypatch: pytest.MonkeyPatch,
    snapshot_payload: dict,
) -> None:
    writes: list[dict] = []

    def fake_bedrock_generate_text(system, user, **_kwargs):
        assert "WEBSITE SNAPSHOT JSON" in user
        return '{"language":"en","market_region":"Romania","category":"SaaS","primary_entities":["Acme"]}'

    monkeypatch.setattr(pre_scan_service, "fetch_url_snapshot", lambda _url: dict(snapshot_payload))
    monkeypatch.setattr(pre_scan_service.semantic_cache_service, "get_json", lambda **_kwargs: None)
    monkeypatch.setattr(
        pre_scan_service.semantic_cache_service,
        "set_json",
        lambda **kwargs: writes.append(kwargs),
    )
    monkeypatch.setattr(pre_scan_service, "bedrock_available", lambda: True)
    monkeypatch.setattr(pre_scan_service, "bedrock_generate_text", fake_bedrock_generate_text)

    result = pre_scan_service.analyze_target("website", "https://example.com", None)

    assert result["source"] == "bedrock_pre_scan"
    assert result["snapshot_title"] == "Acme"
    assert len(writes) == 1
    assert writes[0]["feature_key"] == "audit.pre_scan"
    # Bedrock cutover: pre-scan cache route namespace collapses to "bedrock"
    # (resolve_pre_scan_route -> _bedrock_only_reasoning() is unconditionally True).
    assert writes[0]["route_provider"] == "bedrock"


def test_analyze_url_rejects_challenge_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    challenge_html = """
    <!doctype html>
    <html lang="en-US">
      <head><title>Just a moment...</title></head>
      <body>Enable JavaScript and cookies to continue</body>
    </html>
    """

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html"}
        text = challenge_html

    monkeypatch.setattr(
        pre_scan_service, "safe_sync_fetch", lambda *_args, **_kwargs: FakeResponse()
    )

    with pytest.raises(ValueError, match="Unable to fetch content from URL"):
        pre_scan_service.analyze_target("website", "https://thothgraph.com", None)


def test_analyze_target_brand_without_url(
    monkeypatch: pytest.MonkeyPatch,
    snapshot_payload: dict,
) -> None:
    writes: list[dict] = []

    def fake_bedrock_generate_text(system, user, **_kwargs):
        return '{"language":"en","market_region":"Global","category":"Brand Category","primary_entities":["BrandX"],"competitor_entities":["BrandY"]}'

    monkeypatch.setattr(pre_scan_service.semantic_cache_service, "get_json", lambda **_kwargs: None)
    monkeypatch.setattr(
        pre_scan_service.semantic_cache_service,
        "set_json",
        lambda **kwargs: writes.append(kwargs),
    )
    monkeypatch.setattr(pre_scan_service, "bedrock_available", lambda: True)
    monkeypatch.setattr(pre_scan_service, "bedrock_generate_text", fake_bedrock_generate_text)

    result = pre_scan_service.analyze_target("brand", None, "BrandX")

    assert result["source"] == "bedrock_pre_scan"
    assert result["category"] == "Brand Category"
    assert "BrandY" in result["primary_entities"]
    assert "BrandX" in result["primary_entities"]
