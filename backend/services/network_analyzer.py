import logging
import importlib.util
import time

import httpx

from .observability import (
    ERROR_CODE_TIMEOUT,
    classify_error_code,
    duration_ms,
    is_retryable,
    log_external_service_event,
)

logger = logging.getLogger(__name__)


class NetworkAnalysisService:
    async def analyze_network_protocols(self, url: str) -> dict:
        """
        Analyzes a URL to determine the HTTP version used and infers modern protocol support.
        Note: HTTP/3 detection is complex and often requires specific client capabilities.
        This provides a best-effort analysis based on a standard HTTPS request.
        """
        results = {
            "http_version": "Unknown",
            "supports_http2": False,
            "supports_http3_inferred": False,  # Inferred via alt-svc header
        }

        async def fetch_response(http2_enabled: bool) -> httpx.Response:
            from services.url_validation import safe_async_fetch

            return await safe_async_fetch(
                url,
                method="HEAD",
                timeout=15.0,
                http2=http2_enabled,
            )

        http2_available = importlib.util.find_spec("h2") is not None
        start_time = time.monotonic()
        try:
            try:
                response = await fetch_response(http2_available)
            except (ImportError, RuntimeError):
                logger.info(
                    "HTTP/2 support unavailable for %s; retrying without HTTP/2.",
                    url,
                )
                response = await fetch_response(False)

            results["http_version"] = response.http_version
            if response.http_version in ["HTTP/2", "h2"]:
                results["supports_http2"] = True

            # Check for 'alt-svc' header which advertises HTTP/3 support
            if "alt-svc" in response.headers:
                if "h3" in response.headers["alt-svc"]:
                    results["supports_http3_inferred"] = True

            log_external_service_event(
                logger,
                service="network_analyzer",
                operation="analyze_network_protocols",
                status="success",
                duration_ms_value=duration_ms(start_time),
            )
            return results
        except httpx.TimeoutException as e:
            log_external_service_event(
                logger,
                service="network_analyzer",
                operation="analyze_network_protocols",
                status="error",
                duration_ms_value=duration_ms(start_time),
                error_code=ERROR_CODE_TIMEOUT,
                retryable=True,
                detail=str(e),
            )
            logger.error(f"Network analysis for {url} failed: {e}")
            return results
        except Exception as e:
            error_code = classify_error_code(message=str(e))
            log_external_service_event(
                logger,
                service="network_analyzer",
                operation="analyze_network_protocols",
                status="error",
                duration_ms_value=duration_ms(start_time),
                error_code=error_code,
                retryable=is_retryable(error_code),
                detail=str(e),
            )
            logger.error(f"Network analysis for {url} failed: {e}")
            # Return default values on failure
            return results
