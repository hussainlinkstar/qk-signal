from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

import models
from services.cms_ai_service import _normalize_markdown_body, slugify

from .base_adapter import (
    CMSAdapter,
    CMSChangePreview,
    CMSPushResult,
    build_diff_html,
    validate_supported_field,
)

logger = logging.getLogger(__name__)


class ShopifyAdapter(CMSAdapter):
    def __init__(self, connection: models.CMSConnection):
        self.connection = connection
        self.site_url = str(connection.site_url or "").rstrip("/")
        self.credentials = self._parse_credentials(connection.credentials_json)

    @staticmethod
    def _parse_credentials(raw_credentials: str | None) -> dict[str, str]:
        if not raw_credentials:
            return {}
        try:
            payload = json.loads(raw_credentials)
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key): str(value) for key, value in payload.items() if value is not None}

    @property
    def _token(self) -> str | None:
        return self.credentials.get("access_token") or self.credentials.get("api_token")

    def _headers(self) -> dict[str, str]:
        token = self._token
        if not token:
            return {}
        return {
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        payload: dict[str, object] | None = None,
    ) -> httpx.Response:
        url = f"{self.site_url}{path}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            return await client.request(
                method,
                url,
                headers=self._headers(),
                params=params,
                json=payload,
            )

    async def _resolve_page_id(self, page_url: str) -> int | None:
        parsed = urlparse(page_url)
        segments = [segment for segment in parsed.path.split("/") if segment]
        handle = slugify(segments[-1] if segments else page_url)

        response = await self._request(
            "GET",
            "/admin/api/2024-01/pages.json",
            params={"handle": handle, "limit": "1"},
        )
        if response.status_code >= 400:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        pages = payload.get("pages") if isinstance(payload, dict) else None
        if not isinstance(pages, list) or not pages:
            return None
        page_id = pages[0].get("id")
        return int(page_id) if isinstance(page_id, int) else None

    async def _fetch_current_value(self, page_url: str, field: str) -> str | None:
        if field == "head_scripts":
            return None
        if field == "alt_text":
            return None

        page_id = await self._resolve_page_id(page_url)
        if page_id is None:
            return None
        response = await self._request("GET", f"/admin/api/2024-01/pages/{page_id}.json")
        if response.status_code >= 400:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        page = payload.get("page") if isinstance(payload, dict) else None
        if not isinstance(page, dict):
            return None

        if field == "meta_title":
            value = page.get("title")
            return str(value).strip() if value else None
        if field == "meta_description":
            value = page.get("body_html")
            return str(value).strip() if value else None
        return None

    async def test_connection(self) -> bool:
        if not self.site_url or not self._token:
            return False
        try:
            response = await self._request("GET", "/admin/api/2024-01/shop.json")
        except httpx.HTTPError:
            return False
        return response.status_code < 400

    async def preview_change(
        self,
        *,
        page_url: str,
        field: str,
        new_value: str,
    ) -> CMSChangePreview:
        normalized_field = validate_supported_field(field)
        current_value = await self._fetch_current_value(page_url, normalized_field)
        proposed = (
            _normalize_markdown_body(new_value)
            if normalized_field == "head_scripts"
            else str(new_value)
        )
        return CMSChangePreview(
            page_url=page_url,
            field=normalized_field,
            current_value=current_value,
            proposed_value=proposed,
            diff_html=build_diff_html(current_value, proposed),
        )

    async def push_change(
        self,
        *,
        page_url: str,
        field: str,
        new_value: str,
        approved_by: int,
    ) -> CMSPushResult:
        normalized_field = validate_supported_field(field)
        _ = approved_by

        try:
            if normalized_field in {"meta_title", "meta_description"}:
                page_id = await self._resolve_page_id(page_url)
                if page_id is None:
                    return CMSPushResult(
                        success=False,
                        page_url=page_url,
                        revision_id=None,
                        error_message="Unable to resolve the Shopify page from the target URL.",
                    )

                page_payload: dict[str, object] = {"id": page_id}
                if normalized_field == "meta_title":
                    page_payload["title"] = str(new_value)
                else:
                    page_payload["body_html"] = str(new_value)

                response = await self._request(
                    "PUT",
                    f"/admin/api/2024-01/pages/{page_id}.json",
                    payload={"page": page_payload},
                )
                if response.status_code >= 400:
                    return CMSPushResult(
                        success=False,
                        page_url=page_url,
                        revision_id=None,
                        error_message=f"Shopify page update failed ({response.status_code}).",
                    )

                revision_id = (
                    f"shopify:page:{page_id}:{int(datetime.now(timezone.utc).timestamp())}"
                )
                return CMSPushResult(
                    success=True,
                    page_url=page_url,
                    revision_id=revision_id,
                    error_message=None,
                )

            if normalized_field == "head_scripts":
                response = await self._request(
                    "POST",
                    "/admin/api/2024-01/metafields.json",
                    payload={
                        "metafield": {
                            "namespace": "thothgraph",
                            "key": "head_scripts",
                            "type": "multi_line_text_field",
                            "value": _normalize_markdown_body(new_value),
                        }
                    },
                )
                if response.status_code >= 400:
                    logger.warning(
                        "Shopify head script write failed (connection_id=%s status=%s body=%s)",
                        self.connection.id,
                        response.status_code,
                        response.text,
                    )
                    return CMSPushResult(
                        success=False,
                        page_url=page_url,
                        revision_id=None,
                        error_message=f"Shopify metafield update failed ({response.status_code}).",
                    )
                revision_id = f"shopify:metafield:{int(datetime.now(timezone.utc).timestamp())}"
                return CMSPushResult(
                    success=True,
                    page_url=page_url,
                    revision_id=revision_id,
                    error_message=None,
                )

            return CMSPushResult(
                success=False,
                page_url=page_url,
                revision_id=None,
                error_message="Shopify alt text updates are not supported by this adapter yet.",
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "Shopify push HTTP error (connection_id=%s): %s", self.connection.id, exc
            )
            return CMSPushResult(
                success=False,
                page_url=page_url,
                revision_id=None,
                error_message="Unable to reach Shopify right now.",
            )

    async def rollback_change(self, *, revision_id: str) -> bool:
        # The orchestration layer performs rollback by pushing the previous value.
        return bool(str(revision_id or "").strip())
