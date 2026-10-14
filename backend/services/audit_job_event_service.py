from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0B-\x1F\x7F]")
_WHITESPACE_RE = re.compile(r"\s+")

_PUBLIC_EVENT_NAME_BY_INTERNAL: dict[str, str] = {
    "debate_pipeline_started": "pipeline_started",
    "debate_layer_started": "layer_started",
    "debate_layer_completed": "layer_completed",
    "debate_step_started": "step_started",
    "debate_step_completed": "step_completed",
    "debate_complete": "debate_finished",
}


def build_audit_job_events_key(job_id: str) -> str:
    return f"audit:job:{job_id}:events"


def sanitize_event_text(value: Any, *, max_chars: int = 200) -> str | None:
    if value is None:
        return None
    text = _CONTROL_CHARS_RE.sub(" ", str(value))
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return f"{text[: max(0, max_chars - 3)].rstrip()}..."


_CRITIC_ROLES: set[str] = {
    "challenger",
    "fast_critic",
    "centralized_critic",
    "seo_critic",
    "geo_critic",
    "aeo_critic",
}

_GENERATOR_ROLES: set[str] = {
    "seo_generator",
    "geo_generator",
    "aeo_generator",
    "aeo_geo_generator",
    "fast_proposer",
    "proposer",
}

_GENERATOR_INTERNAL_KEYS: set[str] = {
    "claim_ledger",
}


def _summarize_generator_output(role: str, output: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("seo_findings", "geo_findings", "aeo_findings"):
        findings = output.get(key)
        if isinstance(findings, list) and findings:
            label = key.replace("_", " ").replace("findings", "").strip().upper()
            parts.append(f"{len(findings)} {label} findings")

    claims = output.get("claim_ledger")
    if isinstance(claims, list) and claims:
        parts.append(f"{len(claims)} claims verified")

    citation = output.get("citation_probability_score")
    if isinstance(citation, (int, float)):
        parts.append(f"citation probability {round(citation)}")

    entities = output.get("entity_analysis")
    if isinstance(entities, dict):
        entity_list = entities.get("entities")
        if isinstance(entity_list, list) and entity_list:
            parts.append(f"{len(entity_list)} entities")

    recs = output.get("recommendations")
    if isinstance(recs, list) and recs:
        parts.append(f"{len(recs)} recommendations")

    return ", ".join(parts) + "." if parts else "Analysis complete."


def summarize_debate_output(role: str, output: Any) -> str | None:
    if not isinstance(output, dict):
        return sanitize_event_text(output)

    if isinstance(output.get("summary"), str) and output.get("summary"):
        return sanitize_event_text(output.get("summary"))

    if isinstance(output.get("synthesis_reasoning"), str) and output.get("synthesis_reasoning"):
        return sanitize_event_text(output.get("synthesis_reasoning"))

    if role in _CRITIC_ROLES:
        if "challenges" in output:
            return sanitize_event_text(
                f"{len(output.get('challenges') or [])} challenges, "
                f"{len(output.get('missed_items') or [])} missed items, "
                f"{len(output.get('disagreements') or [])} disagreements."
            )
        return sanitize_event_text(
            f"{len(output.get('unsupported_claims') or [])} unsupported claims, "
            f"{len(output.get('invented_links_or_citations') or [])} invented citations, "
            f"{len(output.get('weak_recommendations') or [])} weak recommendations."
        )

    if role in _GENERATOR_ROLES or "claim_ledger" in output:
        return sanitize_event_text(_summarize_generator_output(role, output))

    public_payload = {
        key: value
        for key, value in output.items()
        if not (isinstance(key, str) and (key.startswith("_") or key in _GENERATOR_INTERNAL_KEYS))
    }
    return sanitize_event_text(json.dumps(public_payload, ensure_ascii=True, default=str))


def normalize_debate_progress_event(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    event_name = str(payload.get("event") or "").strip().lower()
    public_event_name = _PUBLIC_EVENT_NAME_BY_INTERNAL.get(event_name)
    if public_event_name is None:
        return None

    normalized: dict[str, Any] = {
        "type": public_event_name,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }

    for field_name in (
        "role",
        "semantic_role",
        "provider",
        "model",
        "profile",
        "judge_authority",
        "pipeline_type",
        "layer_name",
        "domain",
    ):
        value = payload.get(field_name)
        if isinstance(value, str) and value.strip():
            normalized[field_name] = value.strip()

    for field_name in (
        "layer",
        "total_agents",
        "parallel_layers",
        "estimated_duration_s",
        "agents_in_layer",
        "latency_ms",
        "total_latency_ms",
        "agents_completed",
        "agents_failed",
    ):
        value = payload.get(field_name)
        if isinstance(value, (int, float)):
            normalized[field_name] = max(0, int(value))

    parallel = payload.get("parallel")
    if isinstance(parallel, bool):
        normalized["parallel"] = parallel

    if public_event_name == "step_completed":
        normalized["status"] = "completed"
        summary = sanitize_event_text(payload.get("summary"))
        if summary:
            normalized["summary"] = summary
    elif public_event_name == "debate_finished":
        confidence = payload.get("confidence")
        if isinstance(confidence, (int, float)):
            normalized["confidence_score"] = float(confidence)
        # SIGV2-1024: provider USD stays internal; never forwarded to the
        # customer-facing event stream.
        fallback_reason = sanitize_event_text(payload.get("fallback_reason"), max_chars=120)
        if fallback_reason:
            normalized["fallback_reason"] = fallback_reason

    return normalized


async def append_debate_progress_event(
    redis_client: Any,
    *,
    job_id: str,
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    normalized = normalize_debate_progress_event(payload)
    if normalized is None:
        return None
    await _append_event(redis_client, job_id=job_id, normalized=normalized)
    return normalized


async def _append_event(redis_client: Any, *, job_id: str, normalized: dict[str, Any]) -> None:
    events_key = build_audit_job_events_key(job_id)
    await redis_client.rpush(
        events_key,
        json.dumps(normalized, ensure_ascii=True, default=str),
    )
    # Retention is bounded and explicit (SIGV2-1021, AC3): the evidence list
    # expires AUDIT_JOB_EVENTS_TTL_SECONDS after the last appended event. Once
    # expired, stage history is reconstructed as "unknown" rather than
    # fabricated completion. Best-effort: emission never fails on clients
    # lacking expire.
    expire = getattr(redis_client, "expire", None)
    if callable(expire):
        try:
            await expire(events_key, AUDIT_JOB_EVENTS_TTL_SECONDS)
        except Exception:
            logger.debug("Failed to set events TTL for job %s", job_id)


# ---------------------------------------------------------------------------
# Resumable stage progress (SIGV2-1021)
# ---------------------------------------------------------------------------
# Canonical stage ids for the public audit run view, in pipeline order.
# ``signal_collection`` covers crawl/screenshot/schema fetch; ``measurement``
# covers the parallel performance/network/answerability/geo-visibility/
# competitor gather; ``analysis`` is the AI debate; ``report`` is scoring,
# report assembly and persistence. The in-audit GEO visibility check lives in
# ``measurement`` — there is no separate answer-engine sweep stage because no
# audit runs one (SIGV2-1010 evidence).
AUDIT_STAGE_IDS: tuple[str, ...] = (
    "signal_collection",
    "measurement",
    "analysis",
    "report",
)

AUDIT_STAGE_STATE_PENDING = "pending"
AUDIT_STAGE_STATE_RUNNING = "running"
AUDIT_STAGE_STATE_COMPLETED = "completed"
AUDIT_STAGE_STATE_FAILED = "failed"
AUDIT_STAGE_STATE_SKIPPED = "skipped"
AUDIT_STAGE_STATE_DEGRADED = "degraded"
AUDIT_STAGE_STATE_UNKNOWN = "unknown"

AUDIT_STAGE_STATES: set[str] = {
    AUDIT_STAGE_STATE_PENDING,
    AUDIT_STAGE_STATE_RUNNING,
    AUDIT_STAGE_STATE_COMPLETED,
    AUDIT_STAGE_STATE_FAILED,
    AUDIT_STAGE_STATE_SKIPPED,
    AUDIT_STAGE_STATE_DEGRADED,
    AUDIT_STAGE_STATE_UNKNOWN,
}

# Stage evidence retention: refreshed on every append, 7 days like the
# post-mortem window for failed job hashes.
AUDIT_JOB_EVENTS_TTL_SECONDS = 604_800

_STAGE_EVENT_TYPES = {
    "stage_started",
    "stage_completed",
    "stage_failed",
    "stage_skipped",
}

# Debate events map onto the ``analysis`` stage without any new emission.
_DEBATE_EVENT_STAGE = "analysis"
_DEBATE_EVENTS_MEANING_RUNNING = {
    "pipeline_started",
    "layer_started",
    "step_started",
    "step_completed",
    "layer_completed",
}
_DEBATE_EVENT_MEANING_COMPLETED = "debate_finished"


def normalize_stage_progress_event(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Allowlisted normalization for worker-emitted stage events (AC5).

    Only progress metadata survives: the stage id, the transition, timestamps,
    the job attempt and a short machine reason. Prompts, stack traces, raw
    provider responses and any cost field never reach the public stream.
    """
    if not isinstance(payload, dict):
        return None
    event_type = str(payload.get("event") or "").strip().lower()
    stage_id = str(payload.get("stage") or "").strip().lower()
    if event_type not in _STAGE_EVENT_TYPES or stage_id not in AUDIT_STAGE_IDS:
        return None

    normalized: dict[str, Any] = {
        "type": event_type,
        "stage": stage_id,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }

    attempt = payload.get("attempt")
    if isinstance(attempt, (int, float)) and int(attempt) >= 1:
        normalized["attempt"] = int(attempt)

    # stage_completed may carry a degraded outcome (partial provider failure
    # is degraded, not failed - AC4).
    if event_type == "stage_completed":
        outcome = str(payload.get("outcome") or "").strip().lower()
        if outcome == AUDIT_STAGE_STATE_DEGRADED:
            normalized["outcome"] = AUDIT_STAGE_STATE_DEGRADED

    reason = sanitize_event_text(payload.get("reason"), max_chars=120)
    if reason:
        normalized["reason"] = reason

    summary = sanitize_event_text(payload.get("summary"))
    if summary:
        normalized["summary"] = summary

    return normalized


async def append_stage_progress_event(
    redis_client: Any,
    *,
    job_id: str,
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    normalized = normalize_stage_progress_event(payload)
    if normalized is None:
        return None
    await _append_event(redis_client, job_id=job_id, normalized=normalized)
    return normalized


def project_audit_stage_states(
    events: list[dict[str, Any]] | None,
    *,
    job_status: str | None,
) -> list[dict[str, Any]]:
    """Project retained events + job status onto the canonical stage list.

    Deterministic reconstruction (AC3): events are replayed in append order;
    the last transition for a stage wins; a ``stage_started`` after a terminal
    transition is a distinguishable retry attempt. Job-level failure attributes
    to the stage left in-flight (AC4). Stages with no surviving evidence are
    ``pending`` while the job is queued/in-flight and ``unknown`` otherwise —
    never fabricated as complete.
    """
    status = str(job_status or "").strip().lower()
    events = events or []

    stages: dict[str, dict[str, Any]] = {
        stage_id: {
            "id": stage_id,
            "status": AUDIT_STAGE_STATE_PENDING,
            "attempt": 0,
            "started_at": None,
            "completed_at": None,
            "reason": None,
        }
        for stage_id in AUDIT_STAGE_IDS
    }

    saw_stage_evidence = False
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "").strip().lower()
        if event_type in _DEBATE_EVENTS_MEANING_RUNNING:
            stage_id, state = _DEBATE_EVENT_STAGE, AUDIT_STAGE_STATE_RUNNING
        elif event_type == _DEBATE_EVENT_MEANING_COMPLETED:
            stage_id, state = _DEBATE_EVENT_STAGE, AUDIT_STAGE_STATE_COMPLETED
        elif event_type in _STAGE_EVENT_TYPES:
            stage_id = str(event.get("stage") or "").strip().lower()
            if event_type == "stage_completed" and event.get("outcome") == "degraded":
                state = AUDIT_STAGE_STATE_DEGRADED
            else:
                state = {
                    "stage_started": AUDIT_STAGE_STATE_RUNNING,
                    "stage_completed": AUDIT_STAGE_STATE_COMPLETED,
                    "stage_failed": AUDIT_STAGE_STATE_FAILED,
                    "stage_skipped": AUDIT_STAGE_STATE_SKIPPED,
                }.get(event_type)
        else:
            continue
        if stage_id not in stages or state is None:
            continue

        saw_stage_evidence = True
        stage = stages[stage_id]
        # Retries are distinguishable: a fresh started after a terminal state
        # re-opens the stage and bumps the attempt.
        if state == AUDIT_STAGE_STATE_RUNNING:
            stage["attempt"] += 1
            stage["status"] = AUDIT_STAGE_STATE_RUNNING
            stage["completed_at"] = None
            if isinstance(event.get("occurred_at"), str):
                stage["started_at"] = event["occurred_at"]
        else:
            stage["status"] = state
            if isinstance(event.get("occurred_at"), str):
                stage["completed_at"] = event["occurred_at"]
        if isinstance(event.get("attempt"), int) and event["attempt"] >= 1:
            stage["attempt"] = event["attempt"]
        reason = event.get("reason")
        stage["reason"] = reason if isinstance(reason, str) else stage["reason"]

    if status == "failed":
        # One failure, attributed the same way everywhere: the stage still
        # in-flight when the job died is the failed stage (AC4).
        for stage_id in AUDIT_STAGE_IDS:
            stage = stages[stage_id]
            if stage["status"] == AUDIT_STAGE_STATE_RUNNING:
                stage["status"] = AUDIT_STAGE_STATE_FAILED
                if not stage["reason"]:
                    stage["reason"] = "job_failed"
                break

    if not saw_stage_evidence:
        # Expired or never-recorded evidence: queued jobs truthfully show
        # pending; anything further along is unknown, never fabricated (AC3).
        fallback = (
            AUDIT_STAGE_STATE_PENDING
            if status in {"queued", "running"}
            else AUDIT_STAGE_STATE_UNKNOWN
        )
        for stage in stages.values():
            stage["status"] = fallback
        return list(stages.values())

    # Partial evidence on a terminal job: unevented stages are unknown.
    if status in {"succeeded", "failed"}:
        for stage in stages.values():
            if stage["status"] == AUDIT_STAGE_STATE_PENDING:
                stage["status"] = AUDIT_STAGE_STATE_UNKNOWN
    elif status in {"queued", "running"}:
        # Mid-flight jobs: stages never emitted are pending (stages emit in
        # order, so a silent stage has not started).
        pass

    return list(stages.values())


def encode_sse_event(event_name: str, payload: dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=True, default=str)}\n\n"
