"""Public, unauthenticated guest audit surface for the marketing site.

The marketing site owns ``/signal/guest-audit`` and calls Signal for the
audit itself. Two properties shape everything in this module.

**It cannot be one request.** A guest audit takes tens of seconds. A single
blocking call has been observed returning 502 from the edge while the audit
completed successfully server side, so the browser gets an error for work that
was paid for and succeeded. The public contract is therefore submit plus poll:
``POST`` enqueues and returns a job id, ``GET`` reports
``queued`` / ``running`` / ``completed`` / ``failed``. Job state lives in Redis
with a TTL rather than in Postgres, so no migration is involved and the state
disappears on its own; the claimable ``GuestAuditRecord`` is still written by
the pipeline exactly as before.

**The caller is anonymous and every submission spends money.** So:

* the result is an explicit output allowlist (``project_public_result``),
  built field by field, never a spread of the internal guest payload. A full
  guest payload carries raw model findings, PageSpeed audit internals, network
  diagnostics, entity and competitor lists, the tool and model names used, and
  the internal request id, none of which an anonymous visitor should receive;
* submissions are rate limited per IP under their own key prefix;
* a repeat submission for the same target inside a cooldown window joins the
  job that is already running for it instead of paying twice;
* the queue has a depth ceiling, so a burst is refused at submit time rather
  than accumulating an unbounded amount of paid work.

There is deliberately no total spend ceiling here. Nothing in the repository
caps aggregate guest audit spend today, and inventing one is a product and
budget decision, not an implementation detail.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import Any, Final

from core.config import settings
from core.redis_client import get_async_redis

logger = logging.getLogger(__name__)

JOB_KEY_PREFIX: Final[str] = "guest_audit:job:"
TARGET_KEY_PREFIX: Final[str] = "guest_audit:target:"
RATE_LIMIT_KEY_PREFIX: Final[str] = "guest_audit_public"

STATUS_QUEUED: Final[str] = "queued"
STATUS_RUNNING: Final[str] = "running"
STATUS_COMPLETED: Final[str] = "completed"
STATUS_FAILED: Final[str] = "failed"

TERMINAL_STATUSES: Final[frozenset[str]] = frozenset({STATUS_COMPLETED, STATUS_FAILED})

# Error codes the marketing site can branch on. Anything unexpected collapses
# to ``internal_error`` so an exception message never reaches an anonymous
# caller.
ERROR_TARGET_BLOCKED: Final[str] = "target_blocked"
ERROR_TIMEOUT: Final[str] = "timeout"
ERROR_INTERNAL: Final[str] = "internal_error"

_ERROR_MESSAGES: Final[dict[str, str]] = {
    ERROR_TARGET_BLOCKED: (
        "That address could not be audited. Please check the URL and try again."
    ),
    ERROR_TIMEOUT: "The audit took too long to complete. Please try again.",
    ERROR_INTERNAL: "The audit could not be completed. Please try again.",
}

# Recommendation fields an anonymous caller may see. ``implementation`` is the
# step by step fix and is deliberately excluded: it is the paid product.
# ``source`` names the internal agent that produced the finding and is
# excluded as internal detail.
PUBLIC_RECOMMENDATION_FIELDS: Final[tuple[str, ...]] = ("priority", "title", "description")
MAX_PUBLIC_RECOMMENDATIONS: Final[int] = 5
MAX_PUBLIC_INSIGHTS: Final[int] = 5
MAX_PUBLIC_AIO_INSIGHTS: Final[int] = 4

# Lock metadata an anonymous caller may see. ``capability_key`` and
# ``required_plan`` are internal gating identifiers and stay internal; the
# human readable plan label is enough to render an upgrade prompt.
PUBLIC_LOCK_FIELDS: Final[tuple[str, ...]] = ("is_locked", "required_plan_label", "detail")

PUBLIC_RESULT_FIELDS: Final[tuple[str, ...]] = (
    "schema_version",
    "generated_at",
    "target",
    "scores",
    "score_groups",
    "summary",
    "insights",
    "aio_insights",
    "recommendations",
    "locked_sections",
    "degradation",
    "claim_token",
)

PUBLIC_RESULT_SCHEMA_VERSION: Final[str] = "guest-audit-public/2"


def resolve_job_ttl_seconds() -> int:
    return max(60, int(getattr(settings, "GUEST_AUDIT_JOB_TTL_SECONDS", 1800) or 1800))


def resolve_job_timeout_seconds() -> int:
    return max(30, int(getattr(settings, "GUEST_AUDIT_JOB_TIMEOUT_SECONDS", 300) or 300))


def resolve_poll_interval_ms() -> int:
    return max(500, int(getattr(settings, "GUEST_AUDIT_POLL_INTERVAL_MS", 3000) or 3000))


def resolve_queue_name() -> str:
    return str(
        getattr(settings, "GUEST_AUDIT_QUEUE_NAME", "guest_audit_jobs") or "guest_audit_jobs"
    )


def resolve_max_queue_depth() -> int:
    return max(1, int(getattr(settings, "GUEST_AUDIT_MAX_QUEUE_DEPTH", 50) or 50))


def resolve_target_cooldown_seconds() -> int:
    return max(0, int(getattr(settings, "GUEST_AUDIT_TARGET_COOLDOWN_SECONDS", 900) or 0))


def job_key(job_id: str) -> str:
    return f"{JOB_KEY_PREFIX}{job_id}"


def build_target_fingerprint(
    *,
    audit_target_type: str,
    target_url: str | None,
    target_name: str | None,
) -> str:
    """Stable identity for "the same audit", used for the repeat cooldown."""
    raw = "|".join(
        [
            (audit_target_type or "website").strip().lower(),
            (target_url or "").strip().lower().rstrip("/"),
            (target_name or "").strip().lower(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def public_error(code: str) -> dict[str, str]:
    """Map an internal failure onto a fixed, caller-safe error."""
    normalized = code if code in _ERROR_MESSAGES else ERROR_INTERNAL
    return {"code": normalized, "message": _ERROR_MESSAGES[normalized]}


# ---------------------------------------------------------------------------
# Output allowlist
# ---------------------------------------------------------------------------


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(round(value))
    return None


def _project_target(payload: dict[str, Any]) -> dict[str, Any]:
    target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
    return {
        "type": str(target.get("type") or "website"),
        "name": target.get("name") if isinstance(target.get("name"), str) else None,
        "url": target.get("url") if isinstance(target.get("url"), str) else None,
    }


def _aio_score(payload: dict[str, Any]) -> int | None:
    """The single AI-visibility score: canonical ``metadata.aio`` first, else
    the same weighted roll-up of the stored AEO and GEO component scores."""
    from app.services.aio_view import derive_aio

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    aio_view = metadata.get("aio") if isinstance(metadata.get("aio"), dict) else {}
    explicit = _as_int(aio_view.get("aio_score"))
    if explicit is not None:
        return explicit

    scores = payload.get("scores") if isinstance(payload.get("scores"), dict) else {}
    return _as_int(
        derive_aio({"aeo_score": scores.get("aeo"), "geo_score": scores.get("geo")}).get(
            "aio_score"
        )
    )


def _project_scores(payload: dict[str, Any]) -> dict[str, int | None]:
    scores = payload.get("scores") if isinstance(payload.get("scores"), dict) else {}
    return {
        "overall": _as_int(scores.get("overall")),
        "seo": _as_int(scores.get("seo")),
        "aio": _aio_score(payload),
    }


_AIO_GROUP_MARKERS: Final[tuple[str, ...]] = ("geo", "aeo", "aio")


def _project_score_groups(payload: dict[str, Any]) -> list[dict[str, Any]]:
    groups = payload.get("score_groups")
    if not isinstance(groups, list):
        return []
    projected: list[dict[str, Any]] = []
    aio_group: dict[str, Any] | None = None
    for group in groups:
        if not isinstance(group, dict):
            continue
        label = str(group.get("label") or "")
        if any(marker in label.lower() for marker in _AIO_GROUP_MARKERS):
            if aio_group is None:
                aio_group = {"label": "AIO", "score": _aio_score(payload), "locked": False}
                projected.append(aio_group)
            aio_group["locked"] = aio_group["locked"] or bool(group.get("locked", False))
            continue
        projected.append(
            {
                "label": label,
                "score": _as_int(group.get("score")),
                "locked": bool(group.get("locked", False)),
            }
        )
    return projected


def _project_aio_insights(payload: dict[str, Any]) -> list[str]:
    """AI-visibility insights: AEO/GEO findings first, then the AEO
    improvement strings. Raw finding internals beyond title/description are
    never emitted."""
    analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
    insights: list[str] = []
    for key in ("aeo_findings", "geo_findings"):
        findings = analysis.get(key)
        if not isinstance(findings, list):
            continue
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            title = str(finding.get("title") or "").strip()
            description = str(finding.get("description") or "").strip()
            text = f"{title}. {description}".strip() if description else title
            if text and text not in insights:
                insights.append(text)
    for item in payload.get("aeo_improvements") or []:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text and text not in insights:
            insights.append(text)
    return insights[:MAX_PUBLIC_AIO_INSIGHTS]


def _project_recommendations(payload: dict[str, Any]) -> list[dict[str, str]]:
    raw = payload.get("detailed_seo_recommendations")
    if not isinstance(raw, list):
        return []
    projected: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        entry = {field: str(item.get(field) or "") for field in PUBLIC_RECOMMENDATION_FIELDS}
        if not entry.get("title"):
            continue
        projected.append(entry)
        if len(projected) >= MAX_PUBLIC_RECOMMENDATIONS:
            break
    return projected


def _project_locked_sections(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    locked = metadata.get("locked_sections")
    if not isinstance(locked, dict):
        return {}
    projected: dict[str, dict[str, Any]] = {}
    for name, section in locked.items():
        if not isinstance(section, dict):
            continue
        projected[str(name)] = {
            "is_locked": bool(section.get("is_locked", True)),
            "required_plan_label": (
                str(section.get("required_plan_label"))
                if section.get("required_plan_label")
                else None
            ),
            "detail": str(section.get("detail") or ""),
        }
    return projected


def _project_degradation(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("degradation") if isinstance(payload.get("degradation"), dict) else {}
    reasons: list[dict[str, str]] = []
    for reason in raw.get("reasons") or []:
        if not isinstance(reason, dict):
            continue
        reasons.append(
            {
                "code": str(reason.get("code") or ""),
                "message": str(reason.get("message") or ""),
            }
        )
    return {
        "fully_measured": bool(raw.get("fully_measured", True)),
        "javascript_rendered": bool(raw.get("javascript_rendered", False)),
        "ai_analysis_available": bool(raw.get("ai_analysis_available", False)),
        "reasons": reasons,
    }


def project_public_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Project the internal guest payload onto the public contract.

    Every field is copied one at a time. Nothing is spread, so a later
    addition to the internal payload cannot leak to an anonymous caller by
    accident, which is the same rule the public plan catalog follows.
    """
    if not isinstance(payload, dict):
        return {}

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    insights = [
        str(item) for item in (payload.get("insights") or []) if isinstance(item, str) and item
    ][:MAX_PUBLIC_INSIGHTS]

    result = {
        "schema_version": PUBLIC_RESULT_SCHEMA_VERSION,
        "generated_at": str(metadata.get("created_at") or ""),
        "target": _project_target(payload),
        "scores": _project_scores(payload),
        "score_groups": _project_score_groups(payload),
        "summary": str(payload.get("intelligence_summary") or ""),
        "insights": insights,
        "aio_insights": _project_aio_insights(payload),
        "recommendations": _project_recommendations(payload),
        "locked_sections": _project_locked_sections(payload),
        "degradation": _project_degradation(payload),
        "claim_token": str(payload.get("guest_audit_token") or ""),
    }
    # Defensive: the allowlist is the contract, so refuse to emit a key that
    # is not in it even if this function is edited later.
    return {field: result[field] for field in PUBLIC_RESULT_FIELDS if field in result}


# ---------------------------------------------------------------------------
# Job store (Redis)
# ---------------------------------------------------------------------------


def _decode(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def new_job_id() -> str:
    """Unguessable job id. Holding it is what authorises reading the result."""
    return uuid.uuid4().hex


async def create_job(
    *,
    job_id: str,
    audit_target_type: str,
    target_url: str | None,
    target_name: str | None,
    target_metadata: dict[str, Any] | None,
    email: str | None,
    ip_hash: str,
    user_agent_hash: str | None,
    referrer: str | None,
    request_id: str | None,
    target_fingerprint: str,
) -> None:
    """Persist the queued job and push it onto the guest audit queue.

    Raises ``RuntimeError`` when the queue is at its depth ceiling, so the
    caller can answer 503 instead of accepting work that will not run soon.
    """
    payload = {
        "job_id": job_id,
        "audit_target_type": audit_target_type,
        "target_url": target_url or "",
        "target_name": target_name or "",
        "target_metadata": json.dumps(target_metadata or {}),
        "email": email or "",
        "ip_hash": ip_hash,
        "user_agent_hash": user_agent_hash or "",
        "referrer": referrer or "",
        "request_id": request_id or "",
    }
    ttl = resolve_job_ttl_seconds()
    queue_name = resolve_queue_name()

    async with get_async_redis() as redis_client:
        depth = await redis_client.llen(queue_name)
        if int(depth or 0) >= resolve_max_queue_depth():
            raise RuntimeError("guest audit queue is at capacity")

        await redis_client.hset(
            job_key(job_id),
            mapping={
                **payload,
                "status": STATUS_QUEUED,
                "created_at": str(time.time()),
                "updated_at": str(time.time()),
            },
        )
        await redis_client.expire(job_key(job_id), ttl)
        await redis_client.rpush(queue_name, json.dumps(payload))

        cooldown = resolve_target_cooldown_seconds()
        if cooldown:
            await redis_client.set(
                f"{TARGET_KEY_PREFIX}{target_fingerprint}", job_id, ex=cooldown, nx=True
            )


async def find_job_for_target(target_fingerprint: str) -> str | None:
    """Return the job id already running for this target, if any."""
    if not resolve_target_cooldown_seconds():
        return None
    try:
        async with get_async_redis() as redis_client:
            existing = await redis_client.get(f"{TARGET_KEY_PREFIX}{target_fingerprint}")
            job_id = _decode(existing)
            if not job_id:
                return None
            if not await redis_client.exists(job_key(job_id)):
                return None
            return job_id
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Guest audit target lookup failed: %s", exc)
        return None


async def read_job(job_id: str) -> dict[str, Any] | None:
    async with get_async_redis() as redis_client:
        raw = await redis_client.hgetall(job_key(job_id))
    if not raw:
        return None
    return {
        (_decode(key) or ""): _decode(value)
        for key, value in raw.items()  # type: ignore[union-attr]
    }


async def mark_running(job_id: str) -> None:
    async with get_async_redis() as redis_client:
        await redis_client.hset(
            job_key(job_id),
            mapping={"status": STATUS_RUNNING, "updated_at": str(time.time())},
        )
        await redis_client.expire(job_key(job_id), resolve_job_ttl_seconds())


async def mark_completed(job_id: str, public_result: dict[str, Any]) -> None:
    async with get_async_redis() as redis_client:
        await redis_client.hset(
            job_key(job_id),
            mapping={
                "status": STATUS_COMPLETED,
                "updated_at": str(time.time()),
                "result": json.dumps(public_result),
            },
        )
        await redis_client.expire(job_key(job_id), resolve_job_ttl_seconds())


async def mark_failed(job_id: str, error_code: str) -> None:
    async with get_async_redis() as redis_client:
        await redis_client.hset(
            job_key(job_id),
            mapping={
                "status": STATUS_FAILED,
                "updated_at": str(time.time()),
                "error_code": error_code,
            },
        )
        await redis_client.expire(job_key(job_id), resolve_job_ttl_seconds())


def build_status_payload(job_id: str, record: dict[str, Any]) -> dict[str, Any]:
    """Render a stored job as the public status response.

    A job that is still non-terminal past the job timeout is reported as
    ``failed`` with ``timeout`` rather than leaving the caller polling a job
    whose worker died.
    """
    status = (record.get("status") or STATUS_QUEUED).strip().lower()
    created_at = _safe_float(record.get("created_at"))

    if status not in TERMINAL_STATUSES:
        age = time.time() - created_at if created_at else 0.0
        if age > resolve_job_timeout_seconds():
            status = STATUS_FAILED
            record = {**record, "error_code": ERROR_TIMEOUT}

    payload: dict[str, Any] = {
        "job_id": job_id,
        "status": status,
        "poll_after_ms": 0 if status in TERMINAL_STATUSES else resolve_poll_interval_ms(),
    }

    if status == STATUS_COMPLETED:
        raw_result = record.get("result")
        try:
            parsed = json.loads(raw_result) if raw_result else None
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            payload["result"] = project_public_result_envelope(parsed)
        else:
            payload["status"] = STATUS_FAILED
            payload["error"] = public_error(ERROR_INTERNAL)
    elif status == STATUS_FAILED:
        payload["error"] = public_error(str(record.get("error_code") or ERROR_INTERNAL))

    return payload


def project_public_result_envelope(stored: dict[str, Any]) -> dict[str, Any]:
    """Re-apply the allowlist to a stored result before serving it.

    The stored value was already projected on write. Filtering again on read
    means a payload written by an older build, or tampered with in Redis,
    still cannot introduce a field that is not in the contract.
    """
    return {field: stored[field] for field in PUBLIC_RESULT_FIELDS if field in stored}


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


async def enforce_public_guest_audit_rate_limit(request: Any) -> None:
    """Per IP submit limit, under this endpoint's own key prefix.

    Per IP alone is a weak control when each call spends model money, so it is
    not the only one: submissions also share a per target cooldown and a queue
    depth ceiling. See the module docstring.
    """
    from routers.api_router import (
        _resolve_client_ip,
        enforce_rate_limit,
        parse_rate_limit_config,
    )

    configured_limit, configured_window = parse_rate_limit_config(
        getattr(settings, "RATE_LIMIT_GUEST_AUDIT_PUBLIC", None),
        default_limit=int(getattr(settings, "GUEST_AUDIT_LIMIT", 1) or 1),
        default_window_seconds=int(getattr(settings, "GUEST_AUDIT_WINDOW_SECONDS", 86400) or 86400),
    )
    await enforce_rate_limit(
        key_prefix=RATE_LIMIT_KEY_PREFIX,
        identifier=_resolve_client_ip(request),
        limit=configured_limit,
        window_seconds=configured_window,
        too_many_requests_detail=(
            "Too Many Requests: free audits are limited. Please try again later."
        ),
    )
