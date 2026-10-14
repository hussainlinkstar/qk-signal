import base64
import logging
import os
from pathlib import Path
import time
from typing import Any, Awaitable, Callable


from dotenv import load_dotenv
from firecrawl import AsyncFirecrawlApp
from core.config import settings

from .resilience import CircuitBreaker, ServiceUnavailableError, retry_with_backoff
from .observability import (
    ERROR_CODE_SERVICE_UNAVAILABLE,
    classify_error_code,
    duration_ms,
    is_retryable,
    log_external_service_event,
)
from .screenshot_normalization import normalize_screenshot_base64
from .service_health import record_service_outcome

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fallback scraper constants
# ---------------------------------------------------------------------------
FALLBACK_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
FALLBACK_TIMEOUT = float(os.getenv("FALLBACK_SCRAPER_TIMEOUT", "20"))
FALLBACK_MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB


class ScreenshotNormalizationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


async def normalize_scraped_screenshot(
    payload: Any,
    *,
    fetch_url_bytes: Callable[[str], Awaitable[bytes]] | None = None,
) -> str:
    """Convert Firecrawl screenshot variants into canonical base64.

    Accepts strings and object payloads containing nested screenshot data.
    URL-only payloads are fetched and converted to base64 when ``fetch_url_bytes``
    is available; otherwise a controlled error is raised.
    """

    async def _from_mapping(mapping_payload: dict[str, Any]) -> str:
        for key in ("base64", "data", "screenshot_base64"):
            value = mapping_payload.get(key)
            if isinstance(value, str) and value.strip():
                return await _from_any(value)

        for key in ("image", "screenshot", "payload", "result"):
            nested_payload = mapping_payload.get(key)
            if nested_payload is not None:
                return await _from_any(nested_payload)

        url_value = mapping_payload.get("url")
        if isinstance(url_value, str) and url_value.strip():
            return await _from_any(url_value)

        raise ScreenshotNormalizationError(
            "invalid_screenshot_format",
            "Screenshot payload is missing base64 data.",
        )

    async def _from_any(raw_payload: Any) -> str:
        if isinstance(raw_payload, str):
            candidate = raw_payload.strip()
            if not candidate:
                raise ScreenshotNormalizationError(
                    "invalid_screenshot_format",
                    "Screenshot payload is empty.",
                )

            if candidate.startswith(("http://", "https://")):
                if fetch_url_bytes is None:
                    raise ScreenshotNormalizationError(
                        "invalid_screenshot_format",
                        "Screenshot payload is URL-only and cannot be normalized.",
                    )
                try:
                    image_bytes = await fetch_url_bytes(candidate)
                except ScreenshotNormalizationError:
                    raise
                except Exception as exc:
                    raise ScreenshotNormalizationError(
                        "invalid_screenshot_format",
                        "Failed to fetch screenshot bytes from URL payload.",
                    ) from exc

                if not image_bytes:
                    raise ScreenshotNormalizationError(
                        "invalid_screenshot_format",
                        "Screenshot URL payload resolved to empty content.",
                    )

                encoded_image = base64.b64encode(image_bytes).decode("ascii")
                return normalize_screenshot_base64(encoded_image)

            try:
                return normalize_screenshot_base64(candidate)
            except ValueError as exc:
                raise ScreenshotNormalizationError(
                    "invalid_screenshot_format",
                    "Screenshot payload is not valid base64 data.",
                ) from exc

        if isinstance(raw_payload, dict):
            return await _from_mapping(raw_payload)

        raise ScreenshotNormalizationError(
            "invalid_screenshot_format",
            "Screenshot payload is not a supported format.",
        )

    return await _from_any(payload)


class ScraperService:
    def __init__(self):
        # Lazy-init: don't read the API key at import time.
        # The Firecrawl client is created on first use so that keys
        # loaded later (env/SSM, admin UI) are picked up.
        self._app: AsyncFirecrawlApp | None = None
        self._app_initialized = False
        self.breaker = CircuitBreaker()
        self.retry_config = {
            "retries": self._get_int_env("FIRECRAWL_RETRY_COUNT", 3),
            "base_delay": self._get_float_env("FIRECRAWL_RETRY_BASE_DELAY", 0.5),
            "max_delay": self._get_float_env("FIRECRAWL_RETRY_MAX_DELAY", 4.0),
        }

    @property
    def app(self) -> AsyncFirecrawlApp | None:
        """Lazy-initialize the Firecrawl client on first access."""
        if not self._app_initialized:
            api_key = settings.FIRECRAWL_API_KEY
            self._app = AsyncFirecrawlApp(api_key=api_key) if api_key else None
            self._app_initialized = True
            if self._app:
                logger.info("Firecrawl client initialized (key present)")
            else:
                logger.warning("Firecrawl client not initialized, FIRECRAWL_API_KEY missing")
        return self._app

    def reset_client(self) -> None:
        """Force re-initialization on next access (e.g. after key rotation)."""
        self._app = None
        self._app_initialized = False

    @staticmethod
    def _get_int_env(name: str, default: int) -> int:
        value = os.getenv(name)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            return default

    @staticmethod
    def _get_float_env(name: str, default: float) -> float:
        value = os.getenv(name)
        if value is None:
            return default
        try:
            return float(value)
        except ValueError:
            return default

    def _build_scrape_options(self) -> dict:
        options = {}
        max_age = os.getenv("FIRECRAWL_MAX_AGE")
        timeout = os.getenv("FIRECRAWL_TIMEOUT")
        wait_for = os.getenv("FIRECRAWL_WAIT_FOR")

        if max_age:
            options["maxAge"] = int(max_age)
        if timeout:
            options["timeout"] = int(timeout)
        if wait_for:
            options["waitFor"] = int(wait_for)

        return options

    def _build_error_payload(
        self, error_code: str, message: str, duration_ms_value: int | None = None
    ) -> dict:
        payload = {
            "error_code": error_code,
            "message": message,
        }
        if duration_ms_value is not None:
            payload["duration_ms"] = duration_ms_value
        return payload

    def _classify_error_code(self, error: Exception) -> str:
        if isinstance(error, ServiceUnavailableError):
            return ERROR_CODE_SERVICE_UNAVAILABLE
        return classify_error_code(message=str(error))

    async def _fetch_screenshot_url_bytes(self, screenshot_url: str) -> bytes:
        from services.url_validation import safe_async_fetch

        timeout_s = self._get_float_env("FIRECRAWL_SCREENSHOT_FETCH_TIMEOUT", 15.0)
        response = await safe_async_fetch(screenshot_url, timeout=timeout_s)
        response.raise_for_status()
        return response.content

    # ------------------------------------------------------------------
    # Fallback scraper: httpx + BeautifulSoup + html2text
    # ------------------------------------------------------------------
    async def _fallback_scrape(self, url: str) -> dict:
        """Scrape *url* using httpx and convert HTML to markdown.

        Returns the same dict shape as the Firecrawl happy-path but with
        ``screenshot_base64 = None`` and ``scrape_method = "fallback"``.
        """
        from services.url_validation import safe_async_fetch

        start = time.monotonic()
        try:
            response = await safe_async_fetch(
                url,
                method="GET",
                timeout=FALLBACK_TIMEOUT,
                headers={
                    "User-Agent": FALLBACK_USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            response.raise_for_status()

            content_length = len(response.content)
            if content_length > FALLBACK_MAX_CONTENT_LENGTH:
                raise ValueError(
                    f"Response too large ({content_length} bytes, limit {FALLBACK_MAX_CONTENT_LENGTH})"
                )

            ct = response.headers.get("content-type", "")
            if "html" not in ct.lower():
                raise ValueError(f"Unexpected content-type: {ct}")

            raw_html = response.text

            # --- HTML → Markdown conversion ---
            try:
                from bs4 import BeautifulSoup
                import html2text
            except ImportError as exc:
                raise RuntimeError(
                    "Fallback scraper requires beautifulsoup4 and html2text packages"
                ) from exc

            soup = BeautifulSoup(raw_html, "html.parser")

            # Extract metadata
            title_tag = soup.find("title")
            title = title_tag.get_text(strip=True) if title_tag else ""
            meta_desc_tag = soup.find("meta", attrs={"name": "description"})
            meta_desc = meta_desc_tag.get("content", "") if meta_desc_tag else ""
            canonical_tag = soup.find("link", attrs={"rel": "canonical"})
            canonical = canonical_tag.get("href", "") if canonical_tag else ""
            viewport_tag = soup.find("meta", attrs={"name": "viewport"})
            viewport = viewport_tag.get("content", "") if viewport_tag else ""
            lang = soup.find("html")
            language = lang.get("lang", "") if lang else ""

            # Remove non-content elements
            for tag in soup(
                ["script", "style", "nav", "footer", "header", "aside", "noscript", "iframe"]
            ):
                tag.decompose()

            # Find main content area, or fall back to body
            main_content = (
                soup.find("main")
                or soup.find("article")
                or soup.find("div", {"role": "main"})
                or soup.find("body")
            )
            html_for_conversion = str(main_content) if main_content else str(soup)

            converter = html2text.HTML2Text()
            converter.ignore_links = False
            converter.ignore_images = True
            converter.ignore_emphasis = False
            converter.body_width = 0  # no wrapping
            converter.unicode_snob = True
            markdown_content = converter.handle(html_for_conversion).strip()

            if not markdown_content or len(markdown_content) < 50:
                raise ValueError("Fallback scraper produced insufficient content")

            duration_ms_value = duration_ms(start)
            log_external_service_event(
                logger,
                service="fallback_scraper",
                operation="scrape",
                status="success",
                duration_ms_value=duration_ms_value,
            )

            metadata = {
                "title": title,
                "description": meta_desc,
                "meta_description": meta_desc,
                "canonical": canonical,
                "viewport": viewport,
                "language": language,
                "sourceURL": url,
                "statusCode": response.status_code,
            }

            return {
                "markdown_content": markdown_content,
                "raw_html": raw_html,
                "screenshot_base64": None,
                "metadata": metadata,
                "response_headers": dict(response.headers),
                "success_status": True,
                "url": url,
                "error": None,
                "scrape_method": "fallback",
            }

        except Exception as exc:
            duration_ms_value = duration_ms(start)
            error_code = classify_error_code(message=str(exc))
            log_external_service_event(
                logger,
                service="fallback_scraper",
                operation="scrape",
                status="error",
                duration_ms_value=duration_ms_value,
                error_code=error_code,
                retryable=False,
                detail=str(exc),
            )
            return {
                "error": self._build_error_payload(
                    error_code,
                    f"Fallback scraper failed: {exc}",
                    duration_ms_value,
                ),
                "url": url,
                "success_status": False,
                "scrape_method": "fallback",
            }

    async def get_page_content_and_screenshot(self, url: str):
        """Scrape *url* for markdown content and (optionally) a screenshot.

        Strategy:
        1. Try Firecrawl (full: markdown + screenshot + HTML).
        2. If Firecrawl fails entirely, fall back to httpx + BS4.
        3. If Firecrawl returns markdown but screenshot normalization
           fails, keep the content and mark screenshot as unavailable.
        """
        result = await self._try_firecrawl(url)
        if result["success_status"]:
            return result

        # Firecrawl failed, try lightweight fallback scraper
        firecrawl_error = result.get("error", {})
        logger.warning(
            "Firecrawl scrape failed for %s (code=%s), attempting fallback scraper",
            url,
            firecrawl_error.get("error_code")
            if isinstance(firecrawl_error, dict)
            else firecrawl_error,
        )
        fallback_result = await self._fallback_scrape(url)
        if fallback_result["success_status"]:
            return fallback_result

        # Both scrapers failed, return the Firecrawl error (more informative)
        logger.error(
            "Both Firecrawl and fallback scraper failed for %s",
            url,
        )
        return result

    async def _try_firecrawl(self, url: str) -> dict:
        """Attempt a Firecrawl scrape. Screenshot failures are non-fatal."""
        start_time = time.monotonic()
        try:
            if not self.app:
                duration_ms_value = duration_ms(start_time)
                log_external_service_event(
                    logger,
                    service="firecrawl",
                    operation="scrape",
                    status="error",
                    duration_ms_value=duration_ms_value,
                    error_code="missing_api_key",
                    retryable=False,
                    detail="FIRECRAWL_API_KEY not configured.",
                )
                return {
                    "error": self._build_error_payload(
                        "missing_api_key",
                        "FIRECRAWL_API_KEY not found in environment variables.",
                        duration_ms_value,
                    ),
                    "url": url,
                    "success_status": False,
                }

            async def _scrape():
                return await self.app.scrape(
                    url,
                    formats=["markdown", "screenshot", "html"],
                    only_main_content=True,
                    **self._build_scrape_options(),
                )

            scraped_data = await retry_with_backoff(
                _scrape,
                breaker=self.breaker,
                service_name="Firecrawl",
                retries=self.retry_config["retries"],
                base_delay=self.retry_config["base_delay"],
                max_delay=self.retry_config["max_delay"],
                # Non-retryable errors (e.g. a billing/quota exhaustion 402)
                # should fail straight to the httpx fallback scraper instead
                # of burning through retries + backoff delay that cannot
                # possibly succeed until the account is recharged.
                should_retry=lambda exc: is_retryable(self._classify_error_code(exc)),
                on_retry=lambda exc, attempt, delay: log_external_service_event(
                    logger,
                    service="firecrawl",
                    operation="scrape",
                    status="retrying",
                    duration_ms_value=duration_ms(start_time),
                    error_code=self._classify_error_code(exc),
                    retryable=True,
                    attempt=attempt,
                    delay_s=delay,
                    detail=str(exc),
                ),
            )

            if not scraped_data or not scraped_data.markdown:
                duration_ms_value = duration_ms(start_time)
                log_external_service_event(
                    logger,
                    service="firecrawl",
                    operation="scrape",
                    status="error",
                    duration_ms_value=duration_ms_value,
                    error_code="missing_content",
                    retryable=False,
                    detail="Missing markdown in response.",
                )
                return {
                    "error": self._build_error_payload(
                        "missing_content",
                        "Failed to scrape the URL or markdown content was not found.",
                        duration_ms_value,
                    ),
                    "url": url,
                    "success_status": False,
                }

            # --- Screenshot normalization (non-fatal) ---
            normalized_screenshot_base64 = None
            if scraped_data.screenshot:
                try:
                    normalized_screenshot_base64 = await normalize_scraped_screenshot(
                        scraped_data.screenshot,
                        fetch_url_bytes=self._fetch_screenshot_url_bytes,
                    )
                except ScreenshotNormalizationError as exc:
                    logger.warning(
                        "Screenshot normalization failed for %s (code=%s): %s, continuing without screenshot",
                        url,
                        exc.code,
                        exc,
                    )

            log_external_service_event(
                logger,
                service="firecrawl",
                operation="scrape",
                status="success",
                duration_ms_value=duration_ms(start_time),
            )
            await record_service_outcome("firecrawl", ok=True)
            return {
                "markdown_content": scraped_data.markdown,
                "raw_html": getattr(scraped_data, "html", None),
                "screenshot_base64": normalized_screenshot_base64,
                "metadata": scraped_data.metadata,
                "success_status": True,
                "url": url,
                "error": None,
                "scrape_method": "firecrawl",
            }

        except ServiceUnavailableError as e:
            error_message = str(e)
            duration_ms_value = duration_ms(start_time)
            error_code = self._classify_error_code(e)
            log_external_service_event(
                logger,
                service="firecrawl",
                operation="scrape",
                status="error",
                duration_ms_value=duration_ms_value,
                error_code=error_code,
                retryable=is_retryable(error_code),
                detail=error_message,
            )
            await record_service_outcome("firecrawl", ok=False, detail=error_message)
            return {
                "error": self._build_error_payload(
                    error_code,
                    error_message,
                    duration_ms_value,
                ),
                "url": url,
                "success_status": False,
            }
        except Exception as e:
            error_message = str(e)
            duration_ms_value = duration_ms(start_time)
            error_code = self._classify_error_code(e)
            log_external_service_event(
                logger,
                service="firecrawl",
                operation="scrape",
                status="error",
                duration_ms_value=duration_ms_value,
                error_code=error_code,
                retryable=is_retryable(error_code),
                detail=error_message,
            )
            await record_service_outcome("firecrawl", ok=False, detail=error_message)
            return {
                "error": self._build_error_payload(
                    error_code,
                    error_message,
                    duration_ms_value,
                ),
                "url": url,
                "success_status": False,
            }
