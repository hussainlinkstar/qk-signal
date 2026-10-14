"""DataForSEO SERP Tracking Service.

Integrates with the DataForSEO REST API to track Featured Snippet ownership
and People Also Ask (PAA) appearances for target keywords.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from base64 import b64encode
from datetime import date
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

import models

logger = logging.getLogger(__name__)

# DataForSEO API endpoints
DATAFORSEO_API_BASE = "https://api.dataforseo.com"
SERP_TASK_POST = f"{DATAFORSEO_API_BASE}/v3/serp/google/organic/task_post"
SERP_TASK_GET = f"{DATAFORSEO_API_BASE}/v3/serp/google/organic/task_get/advanced"

# Retry configuration
MAX_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 2.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503}

# Polling configuration for async tasks
TASK_POLL_INTERVAL_SECONDS = 10
TASK_POLL_MAX_ATTEMPTS = 30  # 5 minutes max


class DataForSEOAuthError(Exception):
    """Raised when DataForSEO authentication fails."""


class DataForSEORateLimitError(Exception):
    """Raised when DataForSEO rate limit is hit after all retries."""


class DataForSEOService:
    """Queries DataForSEO SERP API and tracks Featured Snippets & PAA."""

    def __init__(
        self,
        login: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        if not login or not password:
            raise DataForSEOAuthError("DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD are required.")
        self._auth_header = "Basic " + b64encode(f"{login}:{password}".encode()).decode()

    # ------------------------------------------------------------------
    # HTTP helpers with retry
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: Any = None,
    ) -> dict[str, Any]:
        """Make an HTTP request to DataForSEO with retry logic."""
        for attempt in range(MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=60.0) as client:
                    response = client.request(
                        method,
                        url,
                        json=json_body,
                        headers={
                            "Authorization": self._auth_header,
                            "Content-Type": "application/json",
                        },
                    )

                if response.status_code == 200:
                    return response.json()

                if response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY_SECONDS * (2**attempt)
                    logger.warning(
                        "DataForSEO API returned %d, retrying in %.1fs (attempt %d/%d)",
                        response.status_code,
                        delay,
                        attempt + 1,
                        MAX_RETRIES,
                    )
                    time.sleep(delay)
                    continue

                if response.status_code == 401:
                    raise DataForSEOAuthError(f"DataForSEO authentication failed: {response.text}")

                if response.status_code == 429:
                    raise DataForSEORateLimitError(
                        f"DataForSEO rate limit exceeded after {MAX_RETRIES} retries"
                    )

                response.raise_for_status()

            except httpx.RequestError as exc:
                if attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY_SECONDS * (2**attempt)
                    logger.warning(
                        "DataForSEO request error: %s, retrying in %.1fs (attempt %d/%d)",
                        exc,
                        delay,
                        attempt + 1,
                        MAX_RETRIES,
                    )
                    time.sleep(delay)
                    continue
                raise

        raise DataForSEORateLimitError("DataForSEO API exhausted all retries")

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------

    def _post_serp_task(
        self,
        keyword: str,
        language_code: str = "en",
        location_code: Optional[int] = None,
    ) -> str:
        """Post a SERP task and return the task ID."""
        task_data: dict[str, Any] = {
            "keyword": keyword,
            "language_code": language_code,
            "depth": 100,  # Top 100 results
        }
        if location_code:
            task_data["location_code"] = location_code

        response = self._request("POST", SERP_TASK_POST, json_body=[task_data])

        tasks = response.get("tasks", [])
        if not tasks:
            raise ValueError(f"No tasks returned for keyword: {keyword}")

        task = tasks[0]
        status_code = task.get("status_code")
        if status_code != 20100:
            raise ValueError(
                f"DataForSEO task creation failed (status {status_code}): "
                f"{task.get('status_message', 'Unknown error')}"
            )

        task_id = task.get("id")
        if not task_id:
            raise ValueError("DataForSEO returned task without ID")

        logger.info("DataForSEO task posted: keyword=%r task_id=%s", keyword, task_id)
        return task_id

    def _get_serp_result(self, task_id: str) -> dict[str, Any]:
        """Poll and retrieve SERP results for a completed task."""
        url = f"{SERP_TASK_GET}/{task_id}"

        for poll_attempt in range(TASK_POLL_MAX_ATTEMPTS):
            response = self._request("GET", url)

            tasks = response.get("tasks", [])
            if not tasks:
                raise ValueError(f"No result tasks for task_id: {task_id}")

            task = tasks[0]
            status_code = task.get("status_code")

            if status_code == 20000:
                # Task complete
                return task

            if status_code == 40601:
                # Task not ready yet
                logger.debug(
                    "DataForSEO task %s not ready, polling again in %ds",
                    task_id,
                    TASK_POLL_INTERVAL_SECONDS,
                )
                time.sleep(TASK_POLL_INTERVAL_SECONDS)
                continue

            raise ValueError(
                f"DataForSEO task retrieval failed (status {status_code}): "
                f"{task.get('status_message', 'Unknown error')}"
            )

        raise TimeoutError(f"DataForSEO task {task_id} did not complete within polling window")

    # ------------------------------------------------------------------
    # SERP parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _domain_matches(url: str, target_domain: str) -> bool:
        """Check if a URL belongs to the target domain."""
        try:
            parsed = urlparse(url)
            hostname = (parsed.hostname or "").lower().replace("www.", "")
            target = target_domain.lower().replace("www.", "")
            return hostname == target or hostname.endswith(f".{target}")
        except Exception:
            return False

    def _parse_serp_results(
        self,
        task_data: dict[str, Any],
        target_domain: str,
    ) -> dict[str, Any]:
        """Parse SERP task results to detect Featured Snippet and PAA ownership."""
        result = task_data.get("result", [])
        if not result:
            return {
                "owns_featured_snippet": False,
                "featured_snippet_url": None,
                "featured_snippet_content": None,
                "paa_appearances": [],
                "organic_position": None,
                "serp_features_present": [],
                "ai_overview_detected": False,
                "ai_overview_cites_target": False,
                "ai_overview_source_urls": None,
                "ai_overview_text": None,
            }

        items = result[0].get("items", []) if result else []
        serp_features_present: list[str] = []
        owns_featured_snippet = False
        featured_snippet_url: Optional[str] = None
        featured_snippet_content: Optional[str] = None
        paa_appearances: list[dict[str, Any]] = []
        organic_position: Optional[int] = None
        ai_overview_detected = False
        ai_overview_cites_target = False
        ai_overview_source_urls: Optional[list[str]] = None
        ai_overview_text: Optional[str] = None

        for item in items:
            item_type = item.get("type", "")

            # AI Overview / SGE detection
            if item_type in ("ai_overview", "google_ai_overview", "ai_answer"):
                ai_overview_detected = True
                if "ai_overview" not in serp_features_present:
                    serp_features_present.append("ai_overview")

                ai_overview_text = (
                    item.get("text") or item.get("description") or item.get("content") or None
                )

                source_urls: list[str] = []
                for ref in item.get("references") or item.get("items") or []:
                    ref_url = ref.get("url") or ref.get("link") or ""
                    if ref_url:
                        source_urls.append(ref_url)
                        if self._domain_matches(ref_url, target_domain):
                            ai_overview_cites_target = True
                ai_overview_source_urls = source_urls or None

            # Featured Snippet detection (position 0)
            elif item_type == "featured_snippet":
                if "featured_snippet" not in serp_features_present:
                    serp_features_present.append("featured_snippet")

                snippet_url = item.get("url", "")
                if self._domain_matches(snippet_url, target_domain):
                    owns_featured_snippet = True
                    featured_snippet_url = snippet_url
                    featured_snippet_content = item.get("description") or item.get("title") or ""

            # People Also Ask detection
            elif item_type == "people_also_ask":
                if "people_also_ask" not in serp_features_present:
                    serp_features_present.append("people_also_ask")

                paa_items = item.get("items", [])
                if not isinstance(paa_items, list):
                    paa_items = [item]

                for idx, paa_item in enumerate(paa_items):
                    paa_url = paa_item.get("url", "")
                    if self._domain_matches(paa_url, target_domain):
                        paa_appearances.append(
                            {
                                "question": paa_item.get("title", ""),
                                "url": paa_url,
                                "position": idx,
                            }
                        )

            # Organic results, track best position
            elif item_type == "organic":
                if "organic" not in serp_features_present:
                    serp_features_present.append("organic")

                organic_url = item.get("url", "")
                if self._domain_matches(organic_url, target_domain):
                    rank = item.get("rank_absolute")
                    if isinstance(rank, int):
                        if organic_position is None or rank < organic_position:
                            organic_position = rank

            # Track other SERP features
            elif item_type and item_type not in serp_features_present:
                serp_features_present.append(item_type)

        return {
            "owns_featured_snippet": owns_featured_snippet,
            "featured_snippet_url": featured_snippet_url,
            "featured_snippet_content": featured_snippet_content,
            "paa_appearances": paa_appearances,
            "organic_position": organic_position,
            "serp_features_present": serp_features_present,
            "ai_overview_detected": ai_overview_detected,
            "ai_overview_cites_target": ai_overview_cites_target,
            "ai_overview_source_urls": ai_overview_source_urls,
            "ai_overview_text": ai_overview_text,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _upsert_snapshot(
        self,
        db: Session,
        keyword: models.TargetKeyword,
        serp_data: dict[str, Any],
        snapshot_date: date,
        raw_hash: Optional[str] = None,
    ) -> models.SERPTrackingSnapshot:
        """Upsert a SERPTrackingSnapshot for a keyword."""
        existing = (
            db.query(models.SERPTrackingSnapshot)
            .filter(
                models.SERPTrackingSnapshot.keyword_id == keyword.id,
                models.SERPTrackingSnapshot.snapshot_date == snapshot_date,
            )
            .first()
        )

        if existing:
            existing.owns_featured_snippet = serp_data["owns_featured_snippet"]
            existing.featured_snippet_url = serp_data["featured_snippet_url"]
            existing.featured_snippet_content = serp_data["featured_snippet_content"]
            existing.paa_appearances = serp_data["paa_appearances"]
            existing.organic_position = serp_data["organic_position"]
            existing.serp_features_present = serp_data["serp_features_present"]
            existing.ai_overview_detected = serp_data.get("ai_overview_detected", False)
            existing.ai_overview_cites_target = serp_data.get("ai_overview_cites_target", False)
            existing.ai_overview_source_urls = serp_data.get("ai_overview_source_urls")
            existing.ai_overview_text = serp_data.get("ai_overview_text")
            existing.raw_response_hash = raw_hash
            return existing

        snapshot = models.SERPTrackingSnapshot(
            keyword_id=keyword.id,
            project_id=keyword.project_id,
            snapshot_date=snapshot_date,
            owns_featured_snippet=serp_data["owns_featured_snippet"],
            featured_snippet_url=serp_data["featured_snippet_url"],
            featured_snippet_content=serp_data["featured_snippet_content"],
            paa_appearances=serp_data["paa_appearances"],
            organic_position=serp_data["organic_position"],
            serp_features_present=serp_data["serp_features_present"],
            ai_overview_detected=serp_data.get("ai_overview_detected", False),
            ai_overview_cites_target=serp_data.get("ai_overview_cites_target", False),
            ai_overview_source_urls=serp_data.get("ai_overview_source_urls"),
            ai_overview_text=serp_data.get("ai_overview_text"),
            raw_response_hash=raw_hash,
        )
        db.add(snapshot)
        return snapshot

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def check_keyword(
        self,
        db: Session,
        keyword: models.TargetKeyword,
        target_domain: str,
    ) -> models.SERPTrackingSnapshot:
        """Check a single keyword for Featured Snippet / PAA and persist result.

        Returns:
            The upserted SERPTrackingSnapshot.
        """
        logger.info(
            "Checking SERP for keyword=%r project=%d domain=%s",
            keyword.keyword,
            keyword.project_id,
            target_domain,
        )

        task_id = self._post_serp_task(
            keyword=keyword.keyword,
            language_code=keyword.language_code,
            location_code=keyword.location_code,
        )

        task_data = self._get_serp_result(task_id)
        serp_data = self._parse_serp_results(task_data, target_domain)

        # Hash the raw response for change detection
        raw_hash = hashlib.sha256(
            json.dumps(task_data, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

        today = date.today()
        snapshot = self._upsert_snapshot(db, keyword, serp_data, today, raw_hash)
        db.commit()

        logger.info(
            "SERP check complete: keyword=%r snippet=%s paa_count=%d organic_pos=%s",
            keyword.keyword,
            serp_data["owns_featured_snippet"],
            len(serp_data["paa_appearances"]),
            serp_data["organic_position"],
        )

        return snapshot

    def sync_serp_data(
        self,
        db: Session,
        project_id: int,
        target_domain: str,
    ) -> int:
        """Sync SERP data for all active keywords of a project.

        Returns:
            Number of keywords checked.
        """
        keywords = (
            db.query(models.TargetKeyword)
            .filter(
                models.TargetKeyword.project_id == project_id,
                models.TargetKeyword.is_active.is_(True),
            )
            .all()
        )

        if not keywords:
            logger.info("No active keywords for project=%d, skipping SERP sync", project_id)
            return 0

        logger.info(
            "Starting SERP sync for project=%d: %d keywords",
            project_id,
            len(keywords),
        )

        checked = 0
        for kw in keywords:
            try:
                self.check_keyword(db, kw, target_domain)
                checked += 1
            except (DataForSEORateLimitError, DataForSEOAuthError):
                logger.error(
                    "Aborting SERP sync for project=%d due to auth/rate-limit error",
                    project_id,
                )
                raise
            except Exception:
                logger.exception(
                    "Failed to check keyword=%r for project=%d, continuing",
                    kw.keyword,
                    project_id,
                )

        logger.info(
            "SERP sync complete for project=%d: %d/%d keywords checked",
            project_id,
            checked,
            len(keywords),
        )
        return checked
