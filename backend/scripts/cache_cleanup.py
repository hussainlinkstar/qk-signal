#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import httpx
import redis

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.redis_client import get_sync_redis  # noqa: E402

CACHE_TTL_DEFAULT = int(os.getenv("AUDIT_CACHE_TTL_SECONDS", "86400"))
CACHE_TTL_BY_TIER = {
    "fast": int(os.getenv("AUDIT_CACHE_TTL_FAST_SECONDS", str(CACHE_TTL_DEFAULT))),
    "smart": int(os.getenv("AUDIT_CACHE_TTL_SMART_SECONDS", str(CACHE_TTL_DEFAULT))),
}


@dataclass
class CleanupStats:
    scanned: int = 0
    deleted: int = 0
    skipped: int = 0
    errors: int = 0


def get_cache_ttl_seconds(tier: str | None) -> int:
    effective_tier = (tier or "").strip().lower()
    return CACHE_TTL_BY_TIER.get(effective_tier, CACHE_TTL_DEFAULT)


def parse_cached_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fetch_url_signature(url: str) -> dict[str, str] | None:
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        logging.warning("Signature fetch failed for %s: %s", url, exc)
        return None
    content_hash = hashlib.sha256(response.content).hexdigest()
    headers = response.headers
    etag = headers.get("ETag") or headers.get("etag")
    last_modified = headers.get("Last-Modified") or headers.get("last-modified")
    signature = {"content_hash": content_hash}
    if etag:
        signature["etag"] = etag
    if last_modified:
        signature["last_modified"] = last_modified
    return signature


def is_cache_valid(signature: dict[str, str], metadata: dict) -> bool:
    if not signature or not metadata:
        return False
    if metadata.get("etag") and signature.get("etag"):
        return metadata["etag"] == signature["etag"]
    if metadata.get("content_hash") and signature.get("content_hash"):
        return metadata["content_hash"] == signature["content_hash"]
    if metadata.get("last_modified") and signature.get("last_modified"):
        return metadata["last_modified"] == signature["last_modified"]
    return False


def iter_keys(
    redis_client: redis.Redis,
    pattern: str,
    batch_size: int,
    max_keys: int | None,
) -> Iterable[str]:
    cursor: int | str = 0
    seen = 0
    while True:
        cursor, keys = redis_client.scan(cursor=cursor, match=pattern, count=batch_size)
        for key in keys:
            yield key
            seen += 1
            if max_keys is not None and seen >= max_keys:
                return
        if cursor == 0:
            break


def should_delete_for_age(metadata: dict, now: datetime) -> tuple[bool, str | None]:
    cached_at = parse_cached_at(metadata.get("cached_at"))
    if not cached_at:
        return True, "missing cached_at"
    ttl_seconds = get_cache_ttl_seconds(metadata.get("tier"))
    if ttl_seconds <= 0:
        return False, None
    age_seconds = (now - cached_at).total_seconds()
    if age_seconds > ttl_seconds:
        return True, f"age {age_seconds:.0f}s > ttl {ttl_seconds}s"
    return False, None


def should_delete_for_metadata(metadata: dict) -> tuple[bool, str | None]:
    for field in ("url", "provider", "tier"):
        value = metadata.get(field)
        if not isinstance(value, str) or not value.strip():
            return True, f"missing metadata {field}"
    return False, None


def should_delete_for_signature(metadata: dict, skip_signature: bool) -> tuple[bool, str | None]:
    if skip_signature:
        return False, None
    url = metadata.get("url")
    if not isinstance(url, str) or not url.strip():
        return True, "missing url for signature"
    signature = fetch_url_signature(url)
    if signature is None:
        return False, None
    if not is_cache_valid(signature, metadata):
        return True, "metadata signature mismatch"
    return False, None


def cleanup_cache(
    redis_client: redis.Redis,
    pattern: str,
    batch_size: int,
    max_keys: int | None,
    dry_run: bool,
    skip_signature: bool,
) -> CleanupStats:
    stats = CleanupStats()
    now = datetime.now(timezone.utc)

    for key in iter_keys(redis_client, pattern, batch_size, max_keys):
        stats.scanned += 1
        try:
            payload = redis_client.get(key)
            if payload is None:
                reason = "empty payload"
                if not dry_run:
                    redis_client.delete(key)
                logging.info("Deleted %s (%s)", key, reason)
                stats.deleted += 1
                continue

            try:
                entry = json.loads(payload)
            except json.JSONDecodeError:
                reason = "invalid json"
                if not dry_run:
                    redis_client.delete(key)
                logging.info("Deleted %s (%s)", key, reason)
                stats.deleted += 1
                continue

            if not isinstance(entry, dict):
                reason = "unexpected payload"
                if not dry_run:
                    redis_client.delete(key)
                logging.info("Deleted %s (%s)", key, reason)
                stats.deleted += 1
                continue

            metadata = entry.get("metadata") or {}
            if not isinstance(metadata, dict):
                reason = "invalid metadata"
                if not dry_run:
                    redis_client.delete(key)
                logging.info("Deleted %s (%s)", key, reason)
                stats.deleted += 1
                continue

            delete_due_to_metadata, meta_reason = should_delete_for_metadata(metadata)
            if delete_due_to_metadata:
                if not dry_run:
                    redis_client.delete(key)
                logging.info("Deleted %s (%s)", key, meta_reason)
                stats.deleted += 1
                continue

            delete_due_to_age, age_reason = should_delete_for_age(metadata, now)
            if delete_due_to_age:
                if not dry_run:
                    redis_client.delete(key)
                logging.info("Deleted %s (%s)", key, age_reason)
                stats.deleted += 1
                continue

            delete_due_to_signature, sig_reason = should_delete_for_signature(
                metadata, skip_signature
            )
            if delete_due_to_signature:
                if not dry_run:
                    redis_client.delete(key)
                logging.info("Deleted %s (%s)", key, sig_reason)
                stats.deleted += 1
                continue

            stats.skipped += 1
        except Exception as exc:  # noqa: BLE001
            stats.errors += 1
            logging.exception("Error processing %s: %s", key, exc)

    return stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Clean up stale audit cache entries in Redis.")
    parser.add_argument(
        "--pattern",
        default=os.getenv("AUDIT_CACHE_PATTERN", "audit:cache:*"),
        help="Redis key pattern to scan (default: %(default)s)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="SCAN batch size (default: %(default)s)",
    )
    parser.add_argument(
        "--max-keys",
        type=int,
        default=None,
        help="Maximum number of keys to scan (default: unlimited)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log deletions without removing keys",
    )
    parser.add_argument(
        "--skip-signature",
        action="store_true",
        help="Skip live URL signature checks",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    try:
        with get_sync_redis() as redis_client:
            stats = cleanup_cache(
                redis_client=redis_client,
                pattern=args.pattern,
                batch_size=args.batch_size,
                max_keys=args.max_keys,
                dry_run=args.dry_run,
                skip_signature=args.skip_signature,
            )
    except redis.RedisError as exc:
        logging.error("Failed to connect to Redis: %s", exc)
        return 1

    logging.info(
        "Cleanup complete. scanned=%s deleted=%s skipped=%s errors=%s",
        stats.scanned,
        stats.deleted,
        stats.skipped,
        stats.errors,
    )

    return 0 if stats.errors == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
