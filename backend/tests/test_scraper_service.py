from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import services.scraper as scraper_module
from services.scraper import (
    ScraperService,
    ScreenshotNormalizationError,
    normalize_scraped_screenshot,
)


@pytest.mark.asyncio
async def test_normalize_scraped_screenshot_accepts_raw_base64() -> None:
    assert await normalize_scraped_screenshot("-_8") == "+/8="


@pytest.mark.asyncio
async def test_normalize_scraped_screenshot_accepts_data_url() -> None:
    assert (
        await normalize_scraped_screenshot("data:image/png;base64,c2NyZWVuc2hvdA==")
        == "c2NyZWVuc2hvdA=="
    )


@pytest.mark.asyncio
async def test_normalize_scraped_screenshot_accepts_nested_dict_payload() -> None:
    payload = {"image": {"base64": "c2NyZWVuc2hvdA=="}}
    assert await normalize_scraped_screenshot(payload) == "c2NyZWVuc2hvdA=="


@pytest.mark.asyncio
async def test_normalize_scraped_screenshot_fetches_url_payload() -> None:
    async def fake_fetch(_url: str) -> bytes:
        return b"screenshot-bytes"

    encoded = await normalize_scraped_screenshot(
        {"screenshot": {"url": "https://example.com/image.png"}},
        fetch_url_bytes=fake_fetch,
    )

    assert encoded == "c2NyZWVuc2hvdC1ieXRlcw=="


@pytest.mark.asyncio
async def test_normalize_scraped_screenshot_rejects_url_only_without_fetcher() -> None:
    with pytest.raises(ScreenshotNormalizationError) as exc_info:
        await normalize_scraped_screenshot({"screenshot": {"url": "https://example.com/image.png"}})

    assert exc_info.value.code == "invalid_screenshot_format"


@pytest.mark.asyncio
async def test_get_page_content_and_screenshot_fetches_url_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")

    scraper_service = ScraperService()
    scraper_service._fetch_screenshot_url_bytes = AsyncMock(return_value=b"binary-screenshot")
    scraper_service._app = SimpleNamespace(
        scrape=AsyncMock(
            return_value=SimpleNamespace(
                markdown="# Sample",
                screenshot={"url": "https://example.com/shot.png"},
                metadata={"title": "Sample"},
            )
        )
    )
    scraper_service._app_initialized = True

    result = await scraper_service.get_page_content_and_screenshot("https://example.com")

    assert result["success_status"] is True
    assert result["screenshot_base64"] == "YmluYXJ5LXNjcmVlbnNob3Q="
    assert result["scrape_method"] == "firecrawl"


# ---------------------------------------------------------------------------
# Lazy-init tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scraper_lazy_init_defers_key_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Firecrawl client should not be created until first access of .app."""
    monkeypatch.setattr("core.config.settings.FIRECRAWL_API_KEY", None)
    service = ScraperService()
    assert service._app_initialized is False
    assert service.app is None  # triggers lazy-init
    assert service._app_initialized is True


@pytest.mark.asyncio
async def test_scraper_reset_client_re_reads_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """reset_client() should force re-initialization on next .app access."""
    monkeypatch.setattr("core.config.settings.FIRECRAWL_API_KEY", None)
    service = ScraperService()
    assert service.app is None
    service.reset_client()
    assert service._app_initialized is False
    monkeypatch.setattr("core.config.settings.FIRECRAWL_API_KEY", "new-key")
    assert service.app is not None


# ---------------------------------------------------------------------------
# Screenshot decoupling tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_firecrawl_succeeds_without_screenshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Firecrawl returning markdown but no screenshot should still succeed."""
    scraper_service = ScraperService()
    scraper_service._app = SimpleNamespace(
        scrape=AsyncMock(
            return_value=SimpleNamespace(
                markdown="# Hello World\nLots of content here.",
                screenshot=None,
                metadata={"title": "Hello"},
            )
        )
    )
    scraper_service._app_initialized = True

    result = await scraper_service.get_page_content_and_screenshot("https://example.com")

    assert result["success_status"] is True
    assert result["markdown_content"] == "# Hello World\nLots of content here."
    assert result["screenshot_base64"] is None
    assert result["scrape_method"] == "firecrawl"


@pytest.mark.asyncio
async def test_screenshot_normalization_failure_is_non_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A screenshot normalization error should not kill the scrape."""
    scraper_service = ScraperService()
    scraper_service._app = SimpleNamespace(
        scrape=AsyncMock(
            return_value=SimpleNamespace(
                markdown="# Content is fine",
                screenshot="not-valid-base64-!!!",
                metadata={"title": "Page"},
            )
        )
    )
    scraper_service._app_initialized = True

    result = await scraper_service.get_page_content_and_screenshot("https://example.com")

    assert result["success_status"] is True
    assert result["markdown_content"] == "# Content is fine"
    assert result["screenshot_base64"] is None  # gracefully degraded


# ---------------------------------------------------------------------------
# Fallback scraper tests
# ---------------------------------------------------------------------------

SAMPLE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <title>Test Page</title>
    <meta name="description" content="A test description">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="canonical" href="https://example.com/page">
</head>
<body>
    <nav>Skip this</nav>
    <main>
        <h1>Main Content Heading</h1>
        <p>This is the main content of the page with enough text to pass the minimum length check for the fallback scraper validation.</p>
    </main>
    <footer>Skip footer too</footer>
</body>
</html>"""


@pytest.mark.asyncio
async def test_fallback_scrape_success() -> None:
    """Fallback scraper should extract markdown from HTML."""
    scraper_service = ScraperService()

    fake_response = SimpleNamespace(
        status_code=200,
        content=SAMPLE_HTML.encode(),
        text=SAMPLE_HTML,
        headers={"content-type": "text/html; charset=utf-8"},
    )
    fake_response.raise_for_status = lambda: None

    with patch(
        "services.url_validation.safe_async_fetch",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        result = await scraper_service._fallback_scrape("https://example.com/page")

    assert result["success_status"] is True
    assert result["scrape_method"] == "fallback"
    assert result["screenshot_base64"] is None
    assert "Main Content Heading" in result["markdown_content"]
    assert result["metadata"]["title"] == "Test Page"
    assert result["metadata"]["description"] == "A test description"
    assert result["metadata"]["canonical"] == "https://example.com/page"


@pytest.mark.asyncio
async def test_fallback_scrape_non_html_content_type() -> None:
    """Fallback should fail gracefully on non-HTML content."""
    scraper_service = ScraperService()

    fake_response = SimpleNamespace(
        status_code=200,
        content=b'{"json": true}',
        text='{"json": true}',
        headers={"content-type": "application/json"},
    )
    fake_response.raise_for_status = lambda: None

    with patch(
        "services.url_validation.safe_async_fetch",
        new_callable=AsyncMock,
        return_value=fake_response,
    ):
        result = await scraper_service._fallback_scrape("https://example.com/api")

    assert result["success_status"] is False
    assert result["scrape_method"] == "fallback"


@pytest.mark.asyncio
async def test_fallback_triggered_when_firecrawl_fails() -> None:
    """When Firecrawl fails, fallback scraper should be tried."""
    scraper_service = ScraperService()
    scraper_service._app_initialized = True
    scraper_service._app = None  # No Firecrawl

    fallback_result = {
        "markdown_content": "# Fallback Content",
        "raw_html": "<h1>Fallback Content</h1>",
        "screenshot_base64": None,
        "metadata": {"title": "Fallback"},
        "success_status": True,
        "url": "https://example.com",
        "error": None,
        "scrape_method": "fallback",
    }
    scraper_service._fallback_scrape = AsyncMock(return_value=fallback_result)

    result = await scraper_service.get_page_content_and_screenshot("https://example.com")

    assert result["success_status"] is True
    assert result["scrape_method"] == "fallback"
    assert result["markdown_content"] == "# Fallback Content"
    scraper_service._fallback_scrape.assert_awaited_once()


@pytest.mark.asyncio
async def test_quota_exhausted_error_skips_retries_and_falls_back_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A billing/quota error (e.g. Firecrawl 402 insufficient credits) cannot
    succeed on retry, so it should fail straight to the fallback scraper
    instead of burning through the configured retry/backoff attempts."""
    monkeypatch.setattr(scraper_module, "record_service_outcome", AsyncMock())

    scraper_service = ScraperService()
    scraper_service._app_initialized = True
    call_count = 0

    async def failing_scrape(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        raise RuntimeError(
            "Payment Required: Failed to scrape. Insufficient credits to perform this request."
        )

    scraper_service._app = SimpleNamespace(scrape=failing_scrape)
    scraper_service._fallback_scrape = AsyncMock(
        return_value={
            "markdown_content": "# Fallback Content",
            "success_status": True,
            "url": "https://example.com",
            "scrape_method": "fallback",
        }
    )

    result = await scraper_service.get_page_content_and_screenshot("https://example.com")

    assert call_count == 1, "should not have retried a non-retryable billing error"
    assert result["success_status"] is True
    assert result["scrape_method"] == "fallback"


@pytest.mark.asyncio
async def test_firecrawl_success_and_failure_record_service_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every real Firecrawl attempt should update the shared health signal so
    system_checks.py can show real-time degradation, not just key presence."""
    recorded: list[dict] = []

    async def fake_record(service, *, ok, detail=""):
        recorded.append({"service": service, "ok": ok, "detail": detail})

    monkeypatch.setattr(scraper_module, "record_service_outcome", fake_record)

    scraper_service = ScraperService()
    scraper_service._app_initialized = True
    scraper_service._app = SimpleNamespace(
        scrape=AsyncMock(
            return_value=SimpleNamespace(
                markdown="# Hello World",
                screenshot=None,
                metadata={"title": "Hello"},
            )
        )
    )
    await scraper_service.get_page_content_and_screenshot("https://example.com")

    assert recorded == [{"service": "firecrawl", "ok": True, "detail": ""}]

    recorded.clear()
    scraper_service._app = SimpleNamespace(
        scrape=AsyncMock(side_effect=RuntimeError("Payment Required: Insufficient credits"))
    )
    scraper_service._fallback_scrape = AsyncMock(return_value={"success_status": False})

    await scraper_service.get_page_content_and_screenshot("https://example.com")

    assert len(recorded) == 1
    assert recorded[0]["service"] == "firecrawl"
    assert recorded[0]["ok"] is False
    assert "Insufficient credits" in recorded[0]["detail"]


@pytest.mark.asyncio
async def test_firecrawl_error_returned_when_both_fail() -> None:
    """When both Firecrawl and fallback fail, Firecrawl error is returned."""
    scraper_service = ScraperService()
    scraper_service._app_initialized = True
    scraper_service._app = None  # No Firecrawl

    scraper_service._fallback_scrape = AsyncMock(
        return_value={
            "error": {"error_code": "connection_error", "message": "Fallback failed"},
            "url": "https://example.com",
            "success_status": False,
            "scrape_method": "fallback",
        }
    )

    result = await scraper_service.get_page_content_and_screenshot("https://example.com")

    assert result["success_status"] is False
    # Should return the Firecrawl error (missing_api_key), not fallback error
    assert result.get("error", {}).get("error_code") == "missing_api_key"
