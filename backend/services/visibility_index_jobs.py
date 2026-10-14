from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from sqlalchemy.orm import Session

import models
from auth.credits import calculate_audit_credit_cost, decrement_credits_atomic
from core.bedrock_runtime import (
    BedrockModelAccessDeniedError,
    BedrockModelUnavailableError,
    configured_bedrock_region,
    create_bedrock_runtime_client,
    resolve_bedrock_measurement_model,
)
from core.config import settings
from observability import visibility_worker_events_total
from services.ai_search_volatility_service import AISearchVolatilityService
from services.semantic_cache_service import semantic_cache_service
from services.signal_ingestion_service import SignalIngestionService
from services.visibility_scoring import matches_target_domain, normalize_domain, score_response

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r"https?://[^\s\]\)>'\"}]+", re.IGNORECASE)
DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
VISIBILITY_CACHE_FEATURE_KEY = "visibility.prompt_response"
VISIBILITY_CACHE_TIER = "lite"
# Cache routing version. v2 adds engine_source + resolved model id to the
# semantic identity so a Bedrock-proxy entry can never be served as a live
# OpenRouter measurement (and vice versa). v1 entries are orphaned, not read.
VISIBILITY_CACHE_ROUTING_VERSION = "v2"
VISIBILITY_CACHE_TTL_SECONDS = int(os.getenv("VISIBILITY_CACHE_TTL_SECONDS", str(23 * 3600)))

# SIGV2-1300. Why a run was served by the Bedrock panel rather than the engine
# its provider slot names. Persisted on `raw_response.fallback_reason`, so the
# split is answerable per cell and in aggregate instead of only from a log.
LIVE_FALLBACK_DISABLED = "live_measurement_disabled"
LIVE_FALLBACK_NOT_ENTITLED = "plan_not_entitled"
LIVE_FALLBACK_ENGINE_NOT_LIVE = "engine_not_live_measurable"
LIVE_FALLBACK_CALL_FAILED = "live_call_failed"


def _safe_fallback_error(exc: BaseException) -> str:
    """A persistable description of a failed live call.

    `services/openrouter_client` constructs its messages so the API key is
    "never included in raised error messages", and those messages carry the
    HTTP status, which is the detail that makes a quiet downgrade diagnosable.
    Anything else may carry whatever a dependency chose to put in it, so only
    the exception type is recorded: a reason column is not worth a credential
    in the database.
    """
    from services.openrouter_client import OpenRouterError

    if isinstance(exc, OpenRouterError):
        return str(exc)
    return type(exc).__name__


def _is_bedrock_access_denied(exc: BaseException) -> bool:
    """Whether a Bedrock call failed because the caller may not invoke it.

    Read off the botocore error code rather than the exception type, so this
    holds for any client botocore hands back, and off the message only as a
    fallback for a stub that carries no response dict.
    """
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = str((response.get("Error") or {}).get("Code") or "")
        if code == "AccessDeniedException":
            return True
    return "AccessDeniedException" in str(exc)


def _normalize_domain(value: str | None) -> str | None:
    return normalize_domain(value)


def _visibility_credit_adjustment_reason(
    *,
    user_id: int,
    project_id: int,
    topic: str,
    provider: str,
    target_domain: str | None,
    schedule_key: str,
) -> str:
    return json.dumps(
        {
            "kind": "visibility_scheduled_credit_charge",
            "user_id": user_id,
            "project_id": project_id,
            "topic": topic,
            "provider": provider,
            "target_domain": target_domain,
            "schedule_key": schedule_key,
        },
        sort_keys=True,
    )


@dataclass
class ProjectBillingContext:
    """Billing attribution + live-engine entitlement for a visibility run.

    Resolved from the project's *workspace owner* subscription: the visibility
    batch only knows its ``project_id``, so the owning plan is the workspace
    owner's plan. ``live_engine_entitled`` reflects the paid
    ``has_live_engine_tracking`` add-on capability on that plan.
    """

    workspace_id: int | None = None
    user_id: int | None = None
    live_engine_entitled: bool = False


def resolve_project_billing_context(
    db: Session | None, project_id: int | None
) -> ProjectBillingContext:
    """Resolve the workspace-owner billing context + live-engine entitlement.

    Fail-safe: any missing project/workspace/owner (or a DB error) yields the
    default context with ``live_engine_entitled=False`` so live measurement stays
    LOCKED unless the owning plan explicitly grants the add-on.
    """
    if db is None or project_id is None:
        return ProjectBillingContext()

    try:
        project = db.query(models.Project).filter(models.Project.id == project_id).first()
        if project is None:
            return ProjectBillingContext()

        workspace = (
            db.query(models.Workspace).filter(models.Workspace.id == project.workspace_id).first()
        )
        if workspace is None:
            return ProjectBillingContext(workspace_id=project.workspace_id)

        owner = db.query(models.User).filter(models.User.id == workspace.owner_id).first()

        # Lazy import avoids a heavy import chain at module load time.
        from app.services.compliance.plan_validator import PlanValidator

        entitled = PlanValidator().has_feature(owner, "has_live_engine_tracking")
        return ProjectBillingContext(
            workspace_id=project.workspace_id,
            user_id=getattr(workspace, "owner_id", None),
            live_engine_entitled=bool(entitled),
        )
    except Exception:  # pragma: no cover - defensive; never block measurement
        logger.exception("Failed to resolve live-engine entitlement for project_id=%s", project_id)
        return ProjectBillingContext()


@dataclass
class PromptTemplate:
    name: str
    template: str


class ProviderRateLimiter:
    def __init__(self, requests_per_minute: int, sleep_func: Callable[[float], Awaitable[None]]):
        self.requests_per_minute = max(1, requests_per_minute)
        self.sleep_func = sleep_func
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def acquire(self, provider: str) -> None:
        async with self._lock:
            now = time.monotonic()
            window_start = now - 60
            q = self._events[provider]
            while q and q[0] < window_start:
                q.popleft()

            if len(q) < self.requests_per_minute:
                q.append(now)
                return

            sleep_for = max(0.01, 60 - (now - q[0]))
        await self.sleep_func(sleep_for)
        await self.acquire(provider)


class VisibilityIndexJobService:
    def __init__(
        self,
        provider_callable: Callable[[str, str], Awaitable[str | dict[str, Any]]] | None = None,
        sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
        *,
        live_engine_entitled: bool = False,
    ):
        self.provider_callable = provider_callable
        self.sleep_func = sleep_func
        self.max_attempts = int(os.getenv("VISIBILITY_PROVIDER_MAX_ATTEMPTS", "3"))
        self.backoff_base_seconds = float(os.getenv("VISIBILITY_RETRY_BACKOFF_BASE_SECONDS", "1"))
        self.rate_limiter = ProviderRateLimiter(
            requests_per_minute=int(os.getenv("VISIBILITY_PROVIDER_RATE_LIMIT_PER_MIN", "20")),
            sleep_func=sleep_func,
        )
        self.signal_ingestion_service = SignalIngestionService()
        self._bedrock_client: Any | None = None
        self._bedrock_client_region: str | None = None
        # Phase 11.4 — per-run live-engine entitlement. Default OFF (fail-safe):
        # the live OpenRouter panel is only used when the run's owning plan holds
        # the `has_live_engine_tracking` add-on AND the global flag is on.
        # `execute_batch` re-resolves this from the project's workspace owner.
        self.live_engine_entitled = bool(live_engine_entitled)
        # Billing attribution for the live-measurement cost ledger, resolved per
        # batch from the project's workspace owner (workspace_id / owner user_id).
        self._billing_workspace_id: int | None = None
        self._billing_project_id: int | None = None
        self._billing_user_id: int | None = None

    @staticmethod
    def _matches_target_domain(citation: str, target_domain: str | None) -> bool:
        return matches_target_domain(citation, target_domain)

    @staticmethod
    def _extract_citations(text: str) -> list[str]:
        urls = URL_PATTERN.findall(text or "")
        dois = DOI_PATTERN.findall(text or "")
        return [*urls, *dois]

    @staticmethod
    def _is_valid_url(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    @staticmethod
    def _is_valid_doi(value: str) -> bool:
        return bool(DOI_PATTERN.fullmatch(value.strip()))

    def parse_and_validate_citations(
        self, response: str | dict[str, Any]
    ) -> tuple[list[str], list[str], str]:
        if isinstance(response, str):
            text = response
            parsed = self._extract_citations(text)
        else:
            text = self._extract_text_from_payload(response)
            raw_citations = self._extract_citation_candidates(response)
            parsed = [str(item).strip() for item in raw_citations if item]
            if not parsed:
                parsed = self._extract_citations(text)

        valid: list[str] = []
        for citation in parsed:
            if citation.lower().startswith(("http://", "https://")) and self._is_valid_url(
                citation
            ):
                valid.append(citation)
            elif self._is_valid_doi(citation):
                valid.append(citation)
        return parsed, valid, text

    @classmethod
    def _score_response(
        cls,
        topic: str,
        text: str,
        valid_citations: list[str],
        *,
        target_domain: str | None = None,
    ) -> float:
        result = score_response(topic, text, valid_citations, target_domain=target_domain)
        return result.score

    async def _run_provider(self, provider: str, prompt: str) -> str | dict[str, Any]:
        if self.provider_callable:
            return await self.provider_callable(provider, prompt)

        normalized_provider = provider.strip().lower()

        # --- Phase 11: live-engine measurement via OpenRouter (gated OFF) ---
        # Route the neutral visibility query to the REAL consumer model ONLY when
        # BOTH hold:
        #   1. the global `LIVE_ENGINE_MEASUREMENT_ENABLED` flag is on, AND
        #   2. the run's owning plan holds the `has_live_engine_tracking`
        #      capability (`self.live_engine_entitled`, resolved per-batch from the
        #      project's workspace-owner subscription in `execute_batch`).
        # Default (flag off OR not entitled) leaves the Bedrock panel below
        # byte-for-byte unchanged.
        # FIREWALL: only `prompt` (the neutral visibility query built from the
        # public Brand/Category/Problem/Feature/Comparison templates) leaves the
        # system here — no private project context is added.
        live_attempted = False
        # SIGV2-1300: a run that ends up on the proxy records WHY. Without it
        # the divergence between the intended source and the actual one is
        # observable after the fact but never attributed, so "why did this cell
        # fall back" has no answer in the data. Exactly one of these is set.
        fallback_reason: str | None = None
        fallback_error: str | None = None

        if not settings.LIVE_ENGINE_MEASUREMENT_ENABLED:
            fallback_reason = LIVE_FALLBACK_DISABLED
        elif not self.live_engine_entitled:
            fallback_reason = LIVE_FALLBACK_NOT_ENTITLED
        else:
            live_model_id = settings.OPENROUTER_MEASUREMENT_MODEL_MAP.get(normalized_provider)
            if not live_model_id:
                fallback_reason = LIVE_FALLBACK_ENGINE_NOT_LIVE
            else:
                live_attempted = True
                try:
                    return await self._run_openrouter(live_model_id, prompt)
                except Exception as exc:
                    # RESILIENCE: if the live OpenRouter measurement fails (e.g.
                    # HTTP 402 no-credit, rate limit, model unavailable) fall
                    # back to the Bedrock measurement panel below so the run
                    # still succeeds with proxy data instead of degrading to
                    # all-failed. Only the measurement call is affected — the
                    # neutral-prompt firewall is unchanged (same `prompt`).
                    fallback_reason = LIVE_FALLBACK_CALL_FAILED
                    fallback_error = _safe_fallback_error(exc)
                    logger.warning(
                        "live OpenRouter measurement failed for provider=%s (%s); "
                        "falling back to Bedrock panel",
                        normalized_provider,
                        fallback_error,
                        exc_info=True,
                    )
                    visibility_worker_events_total.labels("live_fallback").inc()
                    # fall through to the Bedrock measurement path below

        model_id = resolve_bedrock_measurement_model(normalized_provider)
        if model_id:
            try:
                response = await self._run_bedrock(model_id, prompt)
            except Exception as exc:
                # SIGV2-1313: the proxy is the last resort, so if it also fails
                # the run has no `raw_response` and SIGV2-1300's reason is lost
                # for exactly the case that matters most, a stack where live is
                # off AND the proxy model is denied. Carry it on the exception
                # so `execute_prompt_run` can still record it.
                if fallback_reason:
                    exc.visibility_fallback_reason = fallback_reason  # type: ignore[attr-defined]
                    if fallback_error:
                        exc.visibility_fallback_error = fallback_error  # type: ignore[attr-defined]
                raise
            if isinstance(response, dict) and fallback_reason:
                response["fallback_reason"] = fallback_reason
                if fallback_error:
                    response["fallback_error"] = fallback_error
            return response

        region_overrides = (settings.BEDROCK_MEASUREMENT_MODEL_REGION_OVERRIDES or {}).get(
            configured_bedrock_region(), {}
        )
        known_measurement_provider = (
            normalized_provider in (settings.BEDROCK_MEASUREMENT_MODEL_MAP or {})
            or normalized_provider in region_overrides
        )
        if known_measurement_provider or live_attempted:
            # The engine is a known measurement provider but the configured
            # region cannot serve it (e.g. deepseek/perplexity in Frankfurt,
            # or meta without a Bedrock fallback after a live failure).
            raise BedrockModelUnavailableError(
                f"Measurement unavailable for provider '{provider}' in region "
                f"{configured_bedrock_region()}: "
                + (
                    "OpenRouter request failed and no proxy fallback is configured"
                    if live_attempted
                    else "no proxy model is configured for this region"
                )
            )
        raise ValueError(f"Unsupported provider '{provider}'")

    def _resolve_measurement_identity(self, provider: str) -> tuple[str, str | None]:
        """The (engine_source, model_id) this run INTENDS to measure with.

        Used for the semantic-cache read identity: an OpenRouter-live intent
        must never hit a Bedrock-proxy entry (and vice versa), so the intended
        source is part of the cache key. The WRITE identity comes from the
        actual response instead (see ``_response_identity``) so a live intent
        that fell back to Bedrock is stored under the proxy key it truly is.
        """
        normalized = provider.strip().lower()
        if settings.LIVE_ENGINE_MEASUREMENT_ENABLED and self.live_engine_entitled:
            live_model_id = settings.OPENROUTER_MEASUREMENT_MODEL_MAP.get(normalized)
            if live_model_id:
                return "openrouter_live", live_model_id
        bedrock_model_id = resolve_bedrock_measurement_model(normalized)
        if bedrock_model_id:
            return "bedrock_proxy", bedrock_model_id
        return "unavailable", None

    @staticmethod
    def _response_identity(response: str | dict[str, Any]) -> tuple[str, str | None]:
        """The (engine_source, model_id) a completed response actually is."""
        if isinstance(response, dict):
            source = response.get("engine_source")
            model_id = response.get("model")
            return (
                str(source) if isinstance(source, str) and source else "unknown",
                str(model_id) if isinstance(model_id, str) and model_id else None,
            )
        return "unknown", None

    async def _run_openrouter(self, model_id: str, prompt: str) -> dict[str, Any]:
        """Measurement-only OpenRouter call. Reasoning/debate/Advisor never use
        this path (they stay on Bedrock). The cost is surfaced for the economics
        ledger; key-safety + the neutral-prompt firewall live in the client."""
        from services import openrouter_client

        result = await openrouter_client.query_model(model_id, prompt)
        payload: dict[str, Any] = {
            "answer": result.get("text", ""),
            "usage": result.get("usage", {}),
            "cost": result.get("cost"),
            "model": result.get("model", model_id),
            "engine_source": "openrouter_live",
        }
        # Structured, provider-reported sources must sit at the TOP level: that
        # is where `_extract_citation_candidates` looks. Only fields the
        # provider actually reported are copied, so a provider that reports
        # none still falls back to prose extraction unchanged.
        for field in openrouter_client.CITATION_FIELDS:
            if field in result:
                payload[field] = result[field]
        return payload

    def _record_live_measurement_cost(
        self,
        *,
        db: Session,
        batch: models.VisibilityRunBatch,
        response: str | dict[str, Any],
    ) -> None:
        """Record a live OpenRouter measurement's cost in the AI economics ledger.

        Only fires for live (``openrouter_live``) responses — the Bedrock path is
        accounted for separately and is left untouched. The cost/usage come from
        ``openrouter_client.query_model``. A missing or invalid cost is recorded
        as an explicit UNKNOWN state (``cost_state: "unknown"``, token_cost_usd
        left unset) — never as a measured zero. Zero means the provider truly
        reported a zero cost. Never raises into the measurement flow.
        """
        if not isinstance(response, dict):
            return
        if response.get("engine_source") != "openrouter_live":
            return

        try:
            usage = response.get("usage") or {}
            usage = usage if isinstance(usage, dict) else {}
            input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
            raw_cost = response.get("cost")
            try:
                token_cost = float(raw_cost) if raw_cost is not None else None
            except (TypeError, ValueError):
                token_cost = None

            from services.ai_economics_ledger_service import (
                record_ai_economics_ledger_entry,
            )

            record_ai_economics_ledger_entry(
                db,
                policy_version="",
                feature_key="visibility.live_engine_measurement",
                tier_class="lite",
                routing_profile="openrouter_live",
                provider=str(batch.provider or ""),
                model=str(response.get("model") or ""),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                token_cost_usd=token_cost,
                credits_charged=0,
                workspace_id=self._billing_workspace_id,
                project_id=self._billing_project_id,
                user_id=self._billing_user_id,
                payload={
                    "kind": "visibility_live_engine_measurement",
                    "topic": batch.topic,
                    "engine_source": "openrouter_live",
                    "cost_known": token_cost is not None,
                    "cost_state": "measured" if token_cost is not None else "unknown",
                },
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "Failed to record live-engine measurement cost for batch %s",
                getattr(batch, "id", None),
            )

    async def execute_prompt_run(
        self,
        *,
        db: Session,
        batch: models.VisibilityRunBatch,
        prompt_template: PromptTemplate,
    ) -> models.VisibilityRun:
        prompt = prompt_template.template.format(
            topic=batch.topic,
            provider=batch.provider,
            target_domain=batch.target_domain or "target domain",
        )
        run = models.VisibilityRun(
            batch_id=batch.id,
            topic=batch.topic,
            provider=batch.provider,
            target_domain=batch.target_domain,
            prompt_template=prompt_template.name,
            prompt=prompt,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        intended_source, intended_model = self._resolve_measurement_identity(batch.provider)
        cache_payload = {
            "provider": batch.provider,
            "topic": batch.topic,
            "target_domain": batch.target_domain,
            "prompt_template": prompt_template.name,
            "prompt": prompt,
            "engine_source": intended_source,
            "engine_model": intended_model,
        }
        cache_entry = semantic_cache_service.get_json(
            feature_key=VISIBILITY_CACHE_FEATURE_KEY,
            route_provider=batch.provider,
            route_tier=VISIBILITY_CACHE_TIER,
            semantic_payload=cache_payload,
            version=VISIBILITY_CACHE_ROUTING_VERSION,
        )
        cached_response = cache_entry.get("response") if isinstance(cache_entry, dict) else None
        if isinstance(cached_response, (dict, str)):
            parsed, valid, text = self.parse_and_validate_citations(cached_response)
            score = self._score_response(
                batch.topic,
                text,
                valid,
                target_domain=batch.target_domain,
            )
            run.raw_response = (
                {**cached_response, "served_from_cache": True}
                if isinstance(cached_response, dict)
                else {"text": cached_response, "served_from_cache": True}
            )
            run.parsed_citations = parsed
            run.valid_citations = valid
            run.score = score
            run.status = "succeeded"
            run.error = None
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(run)
            visibility_worker_events_total.labels("run_success").inc()
            return run

        for attempt in range(1, self.max_attempts + 1):
            try:
                await self.rate_limiter.acquire(batch.provider)
                response = await self._run_provider(batch.provider, prompt)
                if isinstance(response, dict):
                    # AC4 provenance: the run and attempt that produced the
                    # measurement, alongside engine_source + model already set
                    # by the engine path.
                    response["run_id"] = run.id
                    response["attempt"] = attempt
                    response["measured_at"] = datetime.now(timezone.utc).isoformat()
                parsed, valid, text = self.parse_and_validate_citations(response)
                score = self._score_response(
                    batch.topic,
                    text,
                    valid,
                    target_domain=batch.target_domain,
                )

                run.raw_response = response if isinstance(response, dict) else {"text": response}
                run.parsed_citations = parsed
                run.valid_citations = valid
                run.score = score
                run.status = "succeeded"
                run.error = None
                run.completed_at = datetime.now(timezone.utc)
                db.commit()
                db.refresh(run)
                cache_value = response if isinstance(response, dict) else {"text": response}
                actual_source, actual_model = self._response_identity(response)
                semantic_cache_service.set_json(
                    feature_key=VISIBILITY_CACHE_FEATURE_KEY,
                    route_provider=batch.provider,
                    route_tier=VISIBILITY_CACHE_TIER,
                    semantic_payload={
                        **cache_payload,
                        "engine_source": actual_source,
                        "engine_model": actual_model,
                    },
                    value=cache_value,
                    ttl_seconds=VISIBILITY_CACHE_TTL_SECONDS,
                    version=VISIBILITY_CACHE_ROUTING_VERSION,
                )
                self._record_live_measurement_cost(db=db, batch=batch, response=response)
                visibility_worker_events_total.labels("run_success").inc()
                return run
            except Exception as exc:
                run.error = str(exc)
                # SIGV2-1313: a failed run has no response to hang provenance
                # on, so the reason travels on the exception. Without this the
                # only case where both paths are unavailable, which is the live
                # stack today, records nothing about why.
                carried_reason = getattr(exc, "visibility_fallback_reason", None)
                if carried_reason:
                    carried: dict[str, Any] = {"fallback_reason": carried_reason}
                    carried_error = getattr(exc, "visibility_fallback_error", None)
                    if carried_error:
                        carried["fallback_error"] = carried_error
                    run.raw_response = carried
                # SIGV2-1301: a denial cannot succeed on a retry, so retrying it
                # three times with backoff only delays the batch and triples the
                # noise. It is terminal, and it is counted separately so a
                # configuration gap is visible as itself rather than buried in
                # the ordinary failure rate.
                access_denied = isinstance(exc, BedrockModelAccessDeniedError)
                if access_denied:
                    run.status = "failed"
                    db.commit()
                    visibility_worker_events_total.labels("run_access_denied").inc()
                    logger.error(
                        "Measurement model '%s' is not invokable by this role in %s; "
                        "this is a configuration fault, not a measurement",
                        exc.model_id,
                        exc.region,
                    )
                    run.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    db.refresh(run)
                    return run
                run.status = "retrying" if attempt < self.max_attempts else "failed"
                db.commit()
                visibility_worker_events_total.labels(
                    "run_retry" if attempt < self.max_attempts else "run_failure"
                ).inc()
                if attempt >= self.max_attempts:
                    run.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    db.refresh(run)
                    return run
                backoff = self.backoff_base_seconds * (2 ** (attempt - 1))
                await self.sleep_func(backoff)

        return run

    async def execute_batch(
        self,
        *,
        db: Session,
        topic: str,
        provider: str,
        prompt_templates: list[PromptTemplate],
        schedule_key: str,
        project_id: int | None = None,
        target_domain: str | None = None,
        charge_user_id: int | None = None,
        charge_credits: bool = False,
        audit_job_id: str | None = None,
    ) -> models.VisibilityRunBatch:
        normalized_target_domain = _normalize_domain(target_domain)
        normalized_provider = provider.strip().lower()
        normalized_topic = str(topic or "").strip()
        if not normalized_topic:
            raise ValueError("Visibility topic is required")

        charge_error: str | None = None
        if charge_credits and charge_user_id is not None and project_id is not None:
            try:
                self._charge_scheduled_visibility_credits(
                    db=db,
                    user_id=charge_user_id,
                    project_id=project_id,
                    topic=normalized_topic,
                    provider=normalized_provider,
                    target_domain=normalized_target_domain,
                    schedule_key=schedule_key,
                )
            except Exception as exc:
                charge_error = str(exc)

        if charge_error is not None:
            failed_batch = models.VisibilityRunBatch(
                project_id=project_id,
                topic=normalized_topic,
                provider=normalized_provider,
                target_domain=normalized_target_domain,
                schedule_key=schedule_key,
                audit_job_id=audit_job_id,
                status="failed",
                score=0.0,
                error=charge_error,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
            db.add(failed_batch)
            db.commit()
            db.refresh(failed_batch)
            visibility_worker_events_total.labels("batch_failure").inc()
            return failed_batch

        batch = models.VisibilityRunBatch(
            project_id=project_id,
            topic=normalized_topic,
            provider=normalized_provider,
            target_domain=normalized_target_domain,
            schedule_key=schedule_key,
            audit_job_id=audit_job_id,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)

        # Phase 11.4 — resolve the live-engine entitlement + billing attribution
        # for this run from the project's workspace owner. Gates the OpenRouter
        # branch in `_run_provider` and supplies the cost-ledger attribution.
        billing_context = resolve_project_billing_context(db, project_id)
        self.live_engine_entitled = billing_context.live_engine_entitled
        self._billing_workspace_id = billing_context.workspace_id
        self._billing_project_id = project_id
        self._billing_user_id = billing_context.user_id

        runs: list[models.VisibilityRun] = []
        for template in prompt_templates:
            run = await self.execute_prompt_run(db=db, batch=batch, prompt_template=template)
            runs.append(run)

        succeeded_scores = [
            run.score for run in runs if run.status == "succeeded" and run.score is not None
        ]
        # A batch with no successful run measured nothing. Writing score 0.0
        # for it published a provider outage as "the brand was not cited":
        # every downstream reader treats a non-failed batch with a numeric
        # score as a completed measurement, so an exhausted retry chain became
        # an absence the customer could see but not explain. ``degraded`` now
        # means what it says - some runs answered, some did not - and a total
        # failure is a failure with no score at all.
        if succeeded_scores:
            batch.score = round(sum(succeeded_scores) / len(succeeded_scores), 2)
            batch.status = (
                "succeeded" if all(run.status == "succeeded" for run in runs) else "degraded"
            )
        else:
            batch.score = None
            batch.status = "failed"
        batch.error = (
            None
            if batch.status == "succeeded"
            else (
                "Every prompt run failed"
                if batch.status == "failed"
                else "One or more prompt runs failed"
            )
        )
        batch.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(batch)

        try:
            self.signal_ingestion_service.ingest_visibility_batch(db=db, batch=batch)
            db.commit()
            db.refresh(batch)
        except Exception:
            db.rollback()
            logger.exception(
                "Signal visibility ingestion failed for batch %s (project_id=%s)",
                batch.id,
                batch.project_id,
            )
            db.refresh(batch)

        try:
            AISearchVolatilityService(db).ingest_visibility_batch(batch=batch)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "Volatility seed run ingestion failed for batch %s (topic=%s provider=%s)",
                batch.id,
                batch.topic,
                batch.provider,
            )
            db.refresh(batch)

        visibility_worker_events_total.labels(
            "batch_success" if batch.status == "succeeded" else "batch_degraded"
        ).inc()
        return batch

    def _charge_scheduled_visibility_credits(
        self,
        *,
        db: Session,
        user_id: int,
        project_id: int,
        topic: str,
        provider: str,
        target_domain: str | None,
        schedule_key: str,
    ) -> int:
        reason = _visibility_credit_adjustment_reason(
            user_id=user_id,
            project_id=project_id,
            topic=topic,
            provider=provider,
            target_domain=target_domain,
            schedule_key=schedule_key,
        )
        existing = (
            db.query(models.UserCreditAdjustment.id)
            .filter(
                models.UserCreditAdjustment.user_id == user_id,
                models.UserCreditAdjustment.reason == reason,
            )
            .first()
        )
        if existing is not None:
            return 0

        credit_cost = max(
            1,
            int(
                calculate_audit_credit_cost(
                    provider=provider,
                    tier="lite",
                    category="visibility_check",
                    market=target_domain,
                )
            ),
        )
        decrement_credits_atomic(db, user_id, credit_cost, allow_negative=True)
        db.add(
            models.UserCreditAdjustment(
                user_id=user_id,
                delta=-credit_cost,
                reason=reason,
            )
        )
        db.commit()
        return credit_cost

    def _get_bedrock_client(self) -> Any:
        if self._bedrock_client is None:
            try:
                import boto3  # noqa: F401 - dependency guard for a clear error
            except ImportError as exc:  # pragma: no cover - optional dependency guard
                raise ValueError("boto3 is required for Bedrock-only measurement") from exc
            self._bedrock_client = create_bedrock_runtime_client()
            self._bedrock_client_region = configured_bedrock_region()
        elif self._bedrock_client_region != configured_bedrock_region():
            # Region flipped since this client was built: rebuild so the new
            # region takes effect without a process restart (SIGV2-1028).
            self._bedrock_client = create_bedrock_runtime_client()
            self._bedrock_client_region = configured_bedrock_region()
        return self._bedrock_client

    async def _run_bedrock(self, model_id: str, prompt: str) -> dict[str, Any]:
        client = self._get_bedrock_client()

        def _converse() -> dict[str, Any]:
            try:
                return client.converse(
                    modelId=model_id,
                    messages=[{"role": "user", "content": [{"text": prompt}]}],
                    inferenceConfig={"maxTokens": 1024, "temperature": 0},
                )
            except Exception as exc:  # noqa: BLE001 - re-raised, narrowed below
                # SIGV2-1301: a denial is a configuration fault and has to be
                # distinguishable from a model that answered badly. Matching on
                # the error code rather than the type keeps this working for any
                # botocore client, and raising our own type drops the role ARN
                # and account id the AWS message carries.
                if _is_bedrock_access_denied(exc):
                    raise BedrockModelAccessDeniedError(
                        model_id, configured_bedrock_region()
                    ) from exc
                raise

        response = await asyncio.to_thread(_converse)

        # Reasoning-block-safe extraction: scan content blocks for the first
        # one carrying a "text" key (GPT-OSS emits separate reasoning blocks).
        answer = ""
        content = response.get("output", {}).get("message", {}).get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    answer = block["text"]
                    break
        return {
            "answer": answer,
            "raw": response,
            "model": model_id,
            "engine_source": "bedrock_proxy",
        }

    @staticmethod
    def _extract_text_from_payload(response: dict[str, Any]) -> str:
        direct = response.get("answer") or response.get("text")
        if isinstance(direct, str) and direct.strip():
            return direct

        content = response.get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item, str):
                    parts.append(item)
            if parts:
                return "\n".join(parts)

        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(message, dict):
                message_content = message.get("content")
                if isinstance(message_content, str):
                    return message_content
                if isinstance(message_content, list):
                    parts = [
                        item.get("text")
                        for item in message_content
                        if isinstance(item, dict) and isinstance(item.get("text"), str)
                    ]
                    if parts:
                        return "\n".join(parts)

        candidates = response.get("candidates")
        if isinstance(candidates, list) and candidates:
            candidate_content = (
                candidates[0].get("content") if isinstance(candidates[0], dict) else None
            )
            if isinstance(candidate_content, dict):
                parts = candidate_content.get("parts")
                if isinstance(parts, list):
                    texts = [
                        item.get("text")
                        for item in parts
                        if isinstance(item, dict) and isinstance(item.get("text"), str)
                    ]
                    if texts:
                        return "\n".join(texts)

        return ""

    @staticmethod
    def _extract_citation_candidates(response: dict[str, Any]) -> list[str]:
        raw_citations = response.get("citations") or response.get("sources") or []
        if isinstance(raw_citations, list) and raw_citations:
            return [str(item).strip() for item in raw_citations if item]

        search_results = response.get("search_results") or response.get("searchResults") or []
        if isinstance(search_results, list) and search_results:
            extracted_search = []
            for item in search_results:
                if not isinstance(item, dict):
                    continue
                candidate_url = item.get("url") or item.get("link")
                if isinstance(candidate_url, str) and candidate_url.strip():
                    extracted_search.append(candidate_url.strip())
            if extracted_search:
                return extracted_search

        # OpenAI-compatible url_citation annotations: OpenRouter standardizes
        # web-search results from every provider into this shape.
        annotations = response.get("annotations") or []
        if isinstance(annotations, list) and annotations:
            extracted_annotations = []
            for item in annotations:
                if not isinstance(item, dict):
                    continue
                url_citation = item.get("url_citation") or item.get("urlCitation") or {}
                candidate_url = url_citation.get("url") if isinstance(url_citation, dict) else None
                if not isinstance(candidate_url, str):
                    candidate_url = item.get("url")
                if isinstance(candidate_url, str) and candidate_url.strip():
                    extracted_annotations.append(candidate_url.strip())
            if extracted_annotations:
                return extracted_annotations

        web_pages = response.get("webPages") or {}
        if isinstance(web_pages, dict):
            values = web_pages.get("value")
            if isinstance(values, list):
                extracted_web_pages = []
                for item in values:
                    if not isinstance(item, dict):
                        continue
                    candidate_url = item.get("url")
                    if isinstance(candidate_url, str) and candidate_url.strip():
                        extracted_web_pages.append(candidate_url.strip())
                if extracted_web_pages:
                    return extracted_web_pages

        grounding_metadata = (
            response.get("groundingMetadata") or response.get("grounding_metadata") or {}
        )
        grounding_chunks = (
            grounding_metadata.get("groundingChunks")
            or grounding_metadata.get("grounding_chunks")
            or []
        )
        extracted: list[str] = []
        if isinstance(grounding_chunks, list):
            for item in grounding_chunks:
                if not isinstance(item, dict):
                    continue
                web = item.get("web") or {}
                if isinstance(web, dict) and isinstance(web.get("uri"), str):
                    extracted.append(web["uri"])
        return extracted


def load_prompt_templates_from_env() -> list[PromptTemplate]:
    raw = os.getenv("VISIBILITY_PROMPT_TEMPLATES_JSON", "").strip()
    if raw:
        payload = json.loads(raw)
        return [PromptTemplate(name=item["name"], template=item["template"]) for item in payload]

    return [
        PromptTemplate(
            name="market_overview",
            template="Which brands are most visible for {topic}? Include sources.",
        ),
        PromptTemplate(
            name="buyer_recommendation",
            template="Recommend top providers for {topic} and cite authoritative references.",
        ),
    ]
