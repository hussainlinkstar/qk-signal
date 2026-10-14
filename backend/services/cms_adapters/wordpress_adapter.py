from __future__ import annotations

import base64
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

HEAD_SCRIPTS_META_KEY = "thothgraph_head_scripts"


def _resolve_head_scripts_meta_key(meta: dict[str, object]) -> str:
    if HEAD_SCRIPTS_META_KEY in meta:
        return HEAD_SCRIPTS_META_KEY
    for key in meta:
        if isinstance(key, str) and key.endswith("_head_scripts"):
            return key
    return HEAD_SCRIPTS_META_KEY


class WordPressAdapter(CMSAdapter):
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

    def _auth_headers(self) -> dict[str, str]:
        username = self.credentials.get("username") or self.credentials.get("user")
        app_password = self.credentials.get("app_password") or self.credentials.get("password")
        bearer = self.credentials.get("access_token")

        if username and app_password:
            token = base64.b64encode(f"{username}:{app_password}".encode("utf-8")).decode("ascii")
            return {"Authorization": f"Basic {token}"}
        if bearer:
            return {"Authorization": f"Bearer {bearer}"}
        return {}

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
                headers=self._auth_headers(),
                params=params,
                json=payload,
            )

    async def _resolve_content_target(self, page_url: str) -> tuple[str | None, int | None]:
        parsed = urlparse(page_url)
        segments = [segment for segment in parsed.path.split("/") if segment]
        slug_hint = slugify(segments[-1] if segments else page_url)

        for content_type in ("pages", "posts"):
            response = await self._request(
                "GET",
                f"/wp-json/wp/v2/{content_type}",
                params={"slug": slug_hint, "per_page": "1"},
            )
            if response.status_code >= 400:
                continue
            try:
                payload = response.json()
            except ValueError:
                continue
            if isinstance(payload, list) and payload:
                target = payload[0]
                target_id = target.get("id")
                if isinstance(target_id, int):
                    return content_type, target_id
        return None, None

    async def _resolve_media_id(self, page_url: str) -> int | None:
        parsed = urlparse(page_url)
        filename = parsed.path.split("/")[-1]
        search_term = filename.rsplit(".", 1)[0] if "." in filename else filename
        if not search_term:
            return None

        response = await self._request(
            "GET",
            "/wp-json/wp/v2/media",
            params={"search": search_term, "per_page": "1"},
        )
        if response.status_code >= 400:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        if not isinstance(payload, list) or not payload:
            return None
        media_id = payload[0].get("id")
        return media_id if isinstance(media_id, int) else None

    async def _fetch_current_value(self, page_url: str, field: str) -> str | None:
        if field == "alt_text":
            media_id = await self._resolve_media_id(page_url)
            if media_id is None:
                return None
            response = await self._request("GET", f"/wp-json/wp/v2/media/{media_id}")
            if response.status_code >= 400:
                return None
            try:
                payload = response.json()
            except ValueError:
                return None
            value = payload.get("alt_text")
            return str(value).strip() if value else None

        content_type, target_id = await self._resolve_content_target(page_url)
        if content_type is None or target_id is None:
            return None

        response = await self._request("GET", f"/wp-json/wp/v2/{content_type}/{target_id}")
        if response.status_code >= 400:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None

        if field == "meta_title":
            rendered = (
                payload.get("title", {}).get("rendered")
                if isinstance(payload.get("title"), dict)
                else None
            )
            return str(rendered).strip() if rendered else None
        if field == "meta_description":
            rendered = (
                payload.get("excerpt", {}).get("rendered")
                if isinstance(payload.get("excerpt"), dict)
                else None
            )
            return str(rendered).strip() if rendered else None
        if field == "head_scripts":
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            head_scripts = (
                meta.get(_resolve_head_scripts_meta_key(meta)) if isinstance(meta, dict) else None
            )
            return str(head_scripts).strip() if head_scripts else None
        return None

    async def test_connection(self) -> bool:
        if not self.site_url:
            return False
        try:
            response = await self._request("GET", "/wp-json/wp/v2/users/me")
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
            if normalized_field == "alt_text":
                media_id = await self._resolve_media_id(page_url)
                if media_id is None:
                    return CMSPushResult(
                        success=False,
                        page_url=page_url,
                        revision_id=None,
                        error_message="Unable to locate WordPress media item for the provided URL.",
                    )
                response = await self._request(
                    "POST",
                    f"/wp-json/wp/v2/media/{media_id}",
                    payload={"alt_text": str(new_value)},
                )
                if response.status_code >= 400:
                    return CMSPushResult(
                        success=False,
                        page_url=page_url,
                        revision_id=None,
                        error_message=f"WordPress media update failed ({response.status_code}).",
                    )
                revision_id = f"wp:media:{media_id}:{int(datetime.now(timezone.utc).timestamp())}"
                return CMSPushResult(
                    success=True,
                    page_url=page_url,
                    revision_id=revision_id,
                    error_message=None,
                )

            content_type, target_id = await self._resolve_content_target(page_url)
            if content_type is None or target_id is None:
                return CMSPushResult(
                    success=False,
                    page_url=page_url,
                    revision_id=None,
                    error_message="Unable to locate WordPress page/post for the provided URL.",
                )

            payload: dict[str, object]
            if normalized_field == "meta_title":
                payload = {"title": str(new_value)}
            elif normalized_field == "meta_description":
                payload = {"excerpt": str(new_value)}
            else:
                payload = {"meta": {HEAD_SCRIPTS_META_KEY: _normalize_markdown_body(new_value)}}

            response = await self._request(
                "POST",
                f"/wp-json/wp/v2/{content_type}/{target_id}",
                payload=payload,
            )
            if response.status_code >= 400:
                logger.warning(
                    "WordPress push failed (connection_id=%s status=%s body=%s)",
                    self.connection.id,
                    response.status_code,
                    response.text,
                )
                return CMSPushResult(
                    success=False,
                    page_url=page_url,
                    revision_id=None,
                    error_message=f"WordPress update failed ({response.status_code}).",
                )

            updated_payload = response.json() if response.content else {}
            modified = (
                updated_payload.get("modified_gmt") if isinstance(updated_payload, dict) else None
            )
            revision_id = f"wp:{content_type}:{target_id}:{modified or int(datetime.now(timezone.utc).timestamp())}"
            return CMSPushResult(
                success=True,
                page_url=page_url,
                revision_id=revision_id,
                error_message=None,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "WordPress push HTTP error (connection_id=%s): %s", self.connection.id, exc
            )
            return CMSPushResult(
                success=False,
                page_url=page_url,
                revision_id=None,
                error_message="Unable to reach WordPress right now.",
            )

    async def rollback_change(self, *, revision_id: str) -> bool:
        # Native revision rollback is CMS-specific and plugin-dependent; the orchestration
        # service performs safe rollback by replaying the previous value through push_change.
        return bool(str(revision_id or "").strip())
