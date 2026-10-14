"""Regression tests for POST /api/v1/site/classify (SIGNAL-1046).

The endpoint used to read ``scrape_result["content"]``, a key ScraperService
never returns (the page text lives under ``markdown_content``). The scrape was
paid for, the content was thrown away, and every response was
``category="General", confidence=0.0``. These tests fail against that bug: the
first one asserts the scraped markdown actually reaches the classifier and the
classifier's answer reaches the caller, the second one keeps the genuine
empty-content short circuit in place.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

import models
from main import app, get_current_user
from routers import api_router


class RecordingClassifierClient:
    def __init__(self, result: dict) -> None:
        self.result = result
        self.contents: list[str] = []

    async def classify_site_category(self, *, content: str, provider: str, tier: str) -> dict:
        del provider, tier
        self.contents.append(content)
        return self.result


def _override_user() -> models.User:
    return models.User(
        id=1,
        email="classify@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )


@pytest.fixture
def classify_client(monkeypatch):
    monkeypatch.setattr(
        api_router.semantic_cache_service,
        "get_json",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        api_router.semantic_cache_service,
        "set_json",
        lambda **kwargs: None,
    )
    app.dependency_overrides[get_current_user] = _override_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_site_classify_uses_scraped_markdown_content(classify_client, monkeypatch) -> None:
    scraped_markdown = "# Bucharest Dental Clinic\n\nWe offer implants and orthodontics."

    async def fake_scrape(url: str) -> dict:
        # Exact ScraperService success shape (services/scraper.py:502-511).
        return {
            "markdown_content": scraped_markdown,
            "raw_html": "<h1>Bucharest Dental Clinic</h1>",
            "screenshot_base64": None,
            "metadata": {"title": "Bucharest Dental Clinic", "sourceURL": url},
            "success_status": True,
            "url": url,
            "error": None,
            "scrape_method": "firecrawl",
        }

    ai_client = RecordingClassifierClient({"category": "Local Business", "confidence": 0.92})
    monkeypatch.setattr(api_router.scraper_service, "get_page_content_and_screenshot", fake_scrape)
    monkeypatch.setattr(api_router, "ai_client", ai_client)

    response = classify_client.post(
        "/api/v1/site/classify",
        json={"url": "https://example.com"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["category"] == "Local Business"
    assert payload["confidence"] == pytest.approx(0.92)

    # The scraped page text must reach the classifier, otherwise the Firecrawl
    # spend is wasted and the answer is a constant.
    assert ai_client.contents, "classifier was never called with the scraped content"
    assert "Bucharest Dental Clinic" in ai_client.contents[0]
    assert "implants and orthodontics" in ai_client.contents[0]


def test_site_classify_returns_general_when_scrape_has_no_content(
    classify_client, monkeypatch
) -> None:
    async def fake_failed_scrape(url: str) -> dict:
        return {
            "error": {"error_code": "missing_content", "message": "no markdown"},
            "url": url,
            "success_status": False,
        }

    ai_client = RecordingClassifierClient({"category": "Local Business", "confidence": 0.92})
    monkeypatch.setattr(
        api_router.scraper_service,
        "get_page_content_and_screenshot",
        fake_failed_scrape,
    )
    monkeypatch.setattr(api_router, "ai_client", ai_client)

    response = classify_client.post(
        "/api/v1/site/classify",
        json={"url": "https://example.com"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["category"] == "General"
    assert payload["confidence"] == 0.0
    assert ai_client.contents == []
