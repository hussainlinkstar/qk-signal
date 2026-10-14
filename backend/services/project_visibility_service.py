from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

import models
from app.config.plans import (
    PLAN_WEIGHTS,
    PRIVATE_PLAN_IDS,
    resolve_entitled_subscription_plan,
    resolve_plan_alias,
)
from auth.credits import calculate_audit_credit_cost
from services.plan_limit_messaging import (
    next_plan_with_higher_allowance,
    plan_display_name,
    tracked_limit_detail,
)
from services.query_taxonomy import (
    CANONICAL_SEARCH_TYPES,
    normalize_search_type,
    resolve_search_type,
    search_type_source,
    suggest_search_type,
)
from services.visibility_refresh_service import (
    VisibilityRefreshResult,
    enqueue_project_visibility_refresh,
    visibility_refresh_in_flight,
)
from services.visibility_scoring import matches_target_domain, score_response

logger = logging.getLogger(__name__)


# The provider VOCABULARY: every key this backend has ever recorded a
# measurement under. It is not the list of engines the product offers - see
# OFFERED_VISIBILITY_PROVIDERS below - because a withdrawn engine's recorded
# rows must keep resolving to a key and a label.
SUPPORTED_VISIBILITY_PROVIDERS: tuple[str, ...] = (
    "google",
    "openai",
    "anthropic",
    "bing",
    "perplexity",
    "xai",
    "deepseek",
    "meta",
)
SUPPORTED_VISIBILITY_QUERY_TYPES: tuple[str, ...] = ("aeo", "geo")

# SIGV2-1215: Copilot leaves the product.
#
# ``bing`` was the only provider outside LIVE_MEASURABLE_PROVIDERS and the only
# key with a LIVE_UNAVAILABLE_REASONS entry: there is no public consumer API
# for Copilot answers, so it could only ever run on the controlled Bedrock
# proxy model, which is not Copilot. Jake took it out of the product on
# 28 September. SIGV2-1188 kept it in every plan roster on purpose, so it would
# not become a visible row that silently never updates; this is the withdrawal
# that pairs the row with the measurement.
#
# This is the one flag. Everything customer-facing enumerates
# OFFERED_VISIBILITY_PROVIDERS or goes through ``_ordered_providers``, which
# drops withdrawn keys, so no surface can present an engine we do not measure.
# What deliberately survives: the key itself, its label, its Bedrock proxy
# mapping in core/config.py, and every recorded measurement. Restoring the
# engine the day a real Copilot API exists means emptying this tuple and
# putting the key back in the plan rosters below - no display code to
# reinstate.
WITHDRAWN_VISIBILITY_PROVIDERS: tuple[str, ...] = ("bing",)


def offered_visibility_providers() -> tuple[str, ...]:
    """The engines the product offers and measures, in canonical order.

    Read from the flag on every call rather than frozen at import, so clearing
    a withdrawal takes effect everywhere at once.
    """
    return tuple(
        provider
        for provider in SUPPORTED_VISIBILITY_PROVIDERS
        if provider not in WITHDRAWN_VISIBILITY_PROVIDERS
    )


# The import-time snapshot, for the recorded contract and for callers that only
# need the current answer once.
OFFERED_VISIBILITY_PROVIDERS: tuple[str, ...] = offered_visibility_providers()

# SIGV2-1186: who wrote a prompt. ``customer`` is also what a NULL ``origin``
# reads as, which is the safe direction: no prompt of the customer's is ever
# labelled as ours, and the only rows that predate the column were written by
# the customer or bridged from their own tracked queries.
ORIGIN_CUSTOMER = "customer"
ORIGIN_GENERATED = "generated"
VISIBILITY_QUERY_ORIGINS: tuple[str, ...] = (ORIGIN_CUSTOMER, ORIGIN_GENERATED)
# The engine a bridged legacy tracker row is written against, and the engine
# the bridge requires the plan to measure before it will run at all.
#
# SIGV2-1216 narrowed what that means without touching this code: Specialist
# no longer measures ``google``, so Executive is now the only plan the bridge
# runs on. It already no-opped on Starter, Standard and the agency trial,
# whose rosters have never included Gemini. Left as is deliberately, because
# making the bridge pick each plan's own engine would start creating prompt
# rows on plans that have never had them, which is a different decision from
# this ticket's. Worth revisiting as its own change.
LEGACY_BRIDGE_PROVIDER = "google"
LEGACY_BRIDGE_MAX_ENTRIES_PER_TYPE = 100

VISIBILITY_PROVIDER_LABELS: dict[str, str] = {
    "google": "Gemini",
    "openai": "ChatGPT",
    "anthropic": "Claude",
    "bing": "Copilot",
    "perplexity": "Perplexity",
    "xai": "Grok",
    "deepseek": "DeepSeek",
    "meta": "Llama",
}

# Engines that can be measured live via OpenRouter (SIGV2-1023). Bing is
# deliberately absent: there is no public consumer API for Copilot answers on
# OpenRouter, so it can only run on the controlled Bedrock proxy panel.
LIVE_MEASURABLE_PROVIDERS: tuple[str, ...] = (
    "google",
    "openai",
    "anthropic",
    "perplexity",
    "xai",
    "deepseek",
    "meta",
)
LIVE_UNAVAILABLE_REASONS: dict[str, str] = {
    "bing": "no public consumer API for Copilot answers on OpenRouter; measured via the Bedrock proxy panel",
}

# SIGV2-1188: the per-plan measurement policy, settled as cadence-per-plan
# rather than a charge-free cell quota. Prompt cap, engine roster and sweep
# cadence live in this one table and everything else reads from it: the create
# and reactivation paths enforce ``max_queries``, the sweep enumerates only
# the plan's engines and only when the plan's interval has elapsed, and the
# entitlement response carries all three so no client keeps its own copy.
#
# The rosters are price-ordered so each upgrade is visibly worth more, and the
# cadences are what bound the cost: Starter re-measures weekly, Specialist
# every two days, everything else daily. ``OPENROUTER_WEB_SEARCH_ENABLED``
# defaults on only because this table caps the spend - on the previous hourly
# all-engine sweep, web retrieval would have cost more per Executive customer
# than the plan charges.
#
# SIGV2-1216: that justification is only true while the table and the price
# list agree, and for one day they did not. SIGV2-1211 cut Specialist from $399
# to $99 and left this table untouched, which took modelled measurement cost
# from about 20% of the price to about 81% of it - a plan losing money on its
# own main function. The arithmetic, at 150 input and 600 output tokens a cell
# plus about $0.007 a cell in OpenRouter search fees, over a 30-day month, own
# domain only:
#
#   engine      model                 $/M in  $/M out   $/cell
#   openai      gpt-5                   2.50    15.00   0.016375
#   google      gemini-2.5-pro          1.25    10.00   0.013188
#   xai         grok-4.3                1.25     2.50   0.008688
#   perplexity  sonar                   1.00     1.00   0.007750
#   deepseek    deepseek-chat           0.20     0.80   0.007510
#
#   Specialist 50 prompts x 5 engines, daily   $80.26/mo   81% of $99
#   Specialist 50 prompts x 4 engines, 2-day   $30.24/mo   30% of $99
#
# SIGV2-1269: treat the table above as the shape of the argument, not as
# current figures. It was never checked against a live call, and the first real
# OpenRouter run (9 Oct 2026) measured 16,110 input tokens a call against the
# 150 assumed here, because web search injects the retrieved pages back into
# the prompt. Observed cost was $0.052 a call with search on, roughly 3x the
# $0.016 modelled for the most expensive engine, and the search fee is 0.005 to
# 0.014 per call by engine rather than a flat 0.007. Anything quoted off this
# table, inside or outside the codebase, is understated. The ladder needs
# re-deriving from `ai_economics_ledger_entries`, which now records every live
# call with the cost OpenRouter reports, once measurement has been running long
# enough to average.
#
# Two dials move, both approved: the sweep goes to every two days and the
# roster drops to four engines. ``google`` is the engine that leaves, because
# gemini-2.5-pro and gpt-5 cost 5.3 times the other three combined, so only one
# of those two can carry the reduction, and ChatGPT is the one a customer most
# expects to be measured. Dropping any of the cheap three instead leaves the
# plan at about 35%.
VISIBILITY_SWEEP_DAILY_SECONDS = 24 * 3600
VISIBILITY_SWEEP_TWO_DAY_SECONDS = 48 * 3600
VISIBILITY_SWEEP_WEEKLY_SECONDS = 7 * 24 * 3600

# SIGV2-1215: ``bing`` (Copilot) was in every roster until Copilot was
# withdrawn from the product. It is gone from all five, so no plan can offer an
# engine with no measurement path. Restoring it means clearing
# WITHDRAWN_VISIBILITY_PROVIDERS and adding the key back here.
#
# SIGV2-1208 adds ``competitor_sweep_interval_seconds`` as a second, separate
# dial. The project's own domain keeps the cadence above; competitor domains
# re-measure on their own, slower one, because the cost scales with the number
# of competitors tracked (five tracked rivals is five times the cells). It is
# ``None`` on the plans that do not sell competitor analysis at all, where
# competitor cells stay on-demand only, and it lives in this table rather than
# in the worker so the cost ladder stays readable in one place.
VISIBILITY_PLAN_LIMITS: dict[str, dict[str, Any]] = {
    "plan_starter": {
        "max_queries": 10,
        "allowed_providers": ["perplexity"],
        "sweep_interval_seconds": VISIBILITY_SWEEP_WEEKLY_SECONDS,
        "competitor_sweep_interval_seconds": None,
    },
    "plan_agency_trial": {
        "max_queries": 25,
        "allowed_providers": ["perplexity", "deepseek", "xai"],
        "sweep_interval_seconds": VISIBILITY_SWEEP_DAILY_SECONDS,
        "competitor_sweep_interval_seconds": VISIBILITY_SWEEP_WEEKLY_SECONDS,
    },
    "plan_standard": {
        "max_queries": 25,
        "allowed_providers": ["perplexity", "deepseek", "xai"],
        "sweep_interval_seconds": VISIBILITY_SWEEP_DAILY_SECONDS,
        "competitor_sweep_interval_seconds": None,
    },
    "plan_specialist": {
        "max_queries": 50,
        # SIGV2-1216: four engines, not five, and every two days rather than
        # daily. See the cost note above the table for the arithmetic.
        "allowed_providers": ["perplexity", "deepseek", "xai", "openai"],
        "sweep_interval_seconds": VISIBILITY_SWEEP_TWO_DAY_SECONDS,
        "competitor_sweep_interval_seconds": VISIBILITY_SWEEP_WEEKLY_SECONDS,
    },
    "plan_executive": {
        "max_queries": 200,
        "allowed_providers": [
            "perplexity",
            "deepseek",
            "xai",
            "google",
            "openai",
            "anthropic",
            "meta",
        ],
        "sweep_interval_seconds": VISIBILITY_SWEEP_DAILY_SECONDS,
        "competitor_sweep_interval_seconds": VISIBILITY_SWEEP_WEEKLY_SECONDS,
    },
}


def visibility_plan_config(plan: str | None) -> dict[str, Any]:
    """The measurement-policy row for a plan id, defaulting to Starter."""
    return VISIBILITY_PLAN_LIMITS.get(
        str(plan or "plan_starter"), VISIBILITY_PLAN_LIMITS["plan_starter"]
    )


# Cadence is the cost dial, so unlike the commercial prompt caps it is
# configuration rather than code: VISIBILITY_STARTER_SWEEP_SECONDS and friends
# override the table's default per plan without a deploy.
_SWEEP_INTERVAL_OVERRIDE_ENV = {
    plan: f"VISIBILITY_{plan.removeprefix('plan_').upper()}_SWEEP_SECONDS"
    for plan in VISIBILITY_PLAN_LIMITS
}
# The competitor cadence gets the same treatment, on its own variable name so
# the two dials can move independently (SIGV2-1208).
_COMPETITOR_SWEEP_INTERVAL_OVERRIDE_ENV = {
    plan: f"VISIBILITY_{plan.removeprefix('plan_').upper()}_COMPETITOR_SWEEP_SECONDS"
    for plan in VISIBILITY_PLAN_LIMITS
}
_sweep_override_warned: set[str] = set()
_competitor_sweep_override_warned: set[str] = set()


def _interval_with_env_override(
    *,
    env_name: str | None,
    default: int,
    warned_key: str,
    warned: set[str],
) -> int:
    """``default``, or a positive integer override from the environment.

    An absent, unparseable or non-positive override falls back to the default
    and is logged once: an invalid value must never mean "sweep every tick",
    which is the unbounded behaviour SIGV2-1188 removed.
    """
    raw = os.getenv(env_name) if env_name else None
    if raw is None or not str(raw).strip():
        return default
    try:
        override = int(str(raw).strip())
    except ValueError:
        override = 0
    if override <= 0 and warned_key not in warned:
        warned.add(warned_key)
        logger.warning(
            "Ignoring invalid %s=%r for plan %s; using default %ss",
            env_name,
            raw,
            warned_key,
            default,
        )
    return override if override > 0 else default


def plan_sweep_interval_seconds(plan: str | None) -> int:
    """How often the scheduled sweep re-measures a project's own domain."""
    config = visibility_plan_config(plan)
    plan_key = str(plan or "plan_starter")
    return _interval_with_env_override(
        env_name=_SWEEP_INTERVAL_OVERRIDE_ENV.get(plan_key),
        default=int(config.get("sweep_interval_seconds", VISIBILITY_SWEEP_DAILY_SECONDS)),
        warned_key=plan_key,
        warned=_sweep_override_warned,
    )


def plan_competitor_sweep_interval_seconds(plan: str | None) -> int | None:
    """How often the scheduled sweep re-measures this plan's competitor domains.

    ``None`` means the plan has no scheduled competitor measurement, which is
    the case for every plan that does not include competitor analysis. Cadence
    is a cost dial, not an entitlement switch, so an env override can only
    change an interval that already exists: it can never turn the competitor
    sweep on for a plan that does not sell the feature.
    """
    config = visibility_plan_config(plan)
    default = config.get("competitor_sweep_interval_seconds")
    if default is None:
        return None
    plan_key = str(plan or "plan_starter")
    return _interval_with_env_override(
        env_name=_COMPETITOR_SWEEP_INTERVAL_OVERRIDE_ENV.get(plan_key),
        default=int(default),
        warned_key=plan_key,
        warned=_competitor_sweep_override_warned,
    )


def plan_measurement_cadence(plan: str | None) -> str:
    """How often this plan re-measures, as a word rather than a number.

    SIGV2-1216: until Specialist moved to a two-day sweep, every interval
    below a week was reported as ``daily``, which was true of every plan that
    had one. It is not true of a 48-hour sweep, and a cadence field exists
    precisely so a surface can state the real interval instead of implying
    one, so anything between daily and weekly now names its own number of
    days. The same holds above a week: an env override of 14 days used to
    answer ``weekly``, an overclaim, so only an interval that rounds to
    exactly seven days earns the word and anything longer names its own
    count. The count is rounded up, so the answer can only ever understate
    freshness, never overclaim it.
    """
    seconds = plan_sweep_interval_seconds(plan)
    if seconds <= VISIBILITY_SWEEP_DAILY_SECONDS:
        return "daily"
    days = -(-seconds // VISIBILITY_SWEEP_DAILY_SECONDS)
    if days == 7:
        return "weekly"
    return f"every_{days}_days"


def plan_allowed_providers(plan: str | None) -> list[str]:
    """The engine roster a plan may measure, in canonical provider order."""
    return _ordered_providers(visibility_plan_config(plan).get("allowed_providers", []))


def plan_unmeasured_providers(plan: str | None) -> list[str]:
    """Offered engines this plan does not measure (SIGV2-1216).

    Derived from the roster rather than listed anywhere, so it cannot fall out
    of step with ``VISIBILITY_PLAN_LIMITS`` when a row changes. Withdrawn
    engines are in neither list: they are not measured by any plan and not
    offered by the product, which is SIGV2-1215's answer, not this one's.
    """
    measured = set(plan_allowed_providers(plan))
    return [provider for provider in offered_visibility_providers() if provider not in measured]


def next_plan_measuring_provider(plan: str | None, provider: str) -> str | None:
    """The cheapest purchasable plan above ``plan`` whose roster measures ``provider``.

    SIGV2-1228: a roster row for an engine the plan does not measure has to say
    what unlocks it, which is the pattern SIGV2-1221 settled for every other
    plan-gated surface. ``None`` means nothing higher measures it, which is the
    answer on the top plan and the honest answer for an engine no plan rosters.

    Plans in ``PRIVATE_PLAN_IDS`` are skipped for the reason SIGV2-1150
    recorded: the agency trial outranks Starter and carries Standard's roster,
    so a naive search finds it first and tells the customer to buy a plan that
    is not for sale.
    """
    normalized = str(provider).strip().lower()
    if not normalized:
        return None
    current_weight = PLAN_WEIGHTS.get(str(plan or "plan_starter"), 0)
    candidates = [
        (PLAN_WEIGHTS.get(candidate, 0), candidate)
        for candidate in VISIBILITY_PLAN_LIMITS
        if candidate not in PRIVATE_PLAN_IDS
        and PLAN_WEIGHTS.get(candidate, 0) > current_weight
        and normalized in plan_allowed_providers(candidate)
    ]
    if not candidates:
        return None
    return min(candidates)[1]


PENDING_BATCH_STATUSES = {"queued", "running", "retrying"}


def visibility_query_allowances() -> dict[str, int]:
    """The prompt cap ladder, plan id to cap."""
    return {
        plan: int(config.get("max_queries", 0)) for plan, config in VISIBILITY_PLAN_LIMITS.items()
    }


def next_plan_with_more_queries(plan: str) -> tuple[str, int] | None:
    """The cheapest plan above ``plan`` that tracks more prompts.

    A refusal has to be able to name the plan that lifts the cap, and the cap
    ladder lives here, so the answer is derived from it rather than restated in
    the frontend (SIGV2-1142). Returns ``None`` when nothing higher raises it.
    """
    return next_plan_with_higher_allowance(plan, visibility_query_allowances())


# ---------------------------------------------------------------------------
# AIO prompts-table evidence semantics (SIGV2-1010)
# ---------------------------------------------------------------------------
# Every cell the prompts table renders carries an explicit presence state and
# an evidence reference back to the persisted run. Presence comes only from
# successful matching evidence:
#   - domain_citation: a valid citation matched the measured target domain
#   - brand_mention: the response text mentioned the target but cited no domain
#   - measured_absent: a completed measurement found neither
#   - unmeasured: pending / failed / proxy-only data, which is NEVER a
#     live-engine "no" (AC4)
# A null value with a machine-readable reason is correct; an invented rank or
# winner is not (AC5).
PRESENCE_DOMAIN_CITATION = "domain_citation"
PRESENCE_BRAND_MENTION = "brand_mention"
PRESENCE_MEASURED_ABSENT = "measured_absent"
PRESENCE_UNMEASURED = "unmeasured"

# Batch provenance: where the measurement snapshot came from. "scan" means the
# batch is linked to the audit job that triggered it; the other origins are
# non-scan measurements and must keep their real measured_at + source.
MEASUREMENT_ORIGIN_SCAN = "scan"
MEASUREMENT_ORIGIN_SCHEDULED = "scheduled"
MEASUREMENT_ORIGIN_QUEUED = "queued"
MEASUREMENT_ORIGIN_VOLATILITY = "volatility"
MEASUREMENT_ORIGIN_UNKNOWN = "unknown"

# Machine-readable reason codes for values the recorded data cannot supply.
REASON_MEASUREMENT_PENDING = "measurement_pending"
REASON_MEASUREMENT_FAILED = "measurement_failed"
REASON_NO_MEASUREMENT = "no_measurement_recorded"
REASON_PROXY_NOT_LIVE = "proxy_measurement_not_live"
REASON_NO_EVIDENCE = "no_evidence_in_measurement"
REASON_NO_COMPLETED_MEASUREMENTS = "no_completed_measurements"
REASON_TIED_PROVIDERS = "tied_providers"
REASON_ORDINAL_POSITION_NOT_RECORDED = "ordinal_position_not_recorded"
# SIGV2-1228: the engine is offered by the product but outside this project's
# plan roster, so nothing is measuring it and no value may be presented for it.
REASON_NOT_MEASURED_ON_PLAN = "not_measured_on_plan"


def _batch_measurement_origin(batch: models.VisibilityRunBatch) -> str:
    """Classify where a batch came from so scan-linked, scheduled, queued and
    volatility results stay explicitly identified (AC2)."""
    if batch.audit_job_id:
        return MEASUREMENT_ORIGIN_SCAN
    schedule_key = str(batch.schedule_key or "")
    if schedule_key.startswith("volatility:"):
        return MEASUREMENT_ORIGIN_VOLATILITY
    if schedule_key == "queued":
        return MEASUREMENT_ORIGIN_QUEUED
    if schedule_key:
        return MEASUREMENT_ORIGIN_SCHEDULED
    return MEASUREMENT_ORIGIN_UNKNOWN


def _serialize_run_evidence(run: models.VisibilityRun) -> dict[str, Any]:
    """Per-run provenance persisted by SIGV2-1023: the rendered prompt and its
    template version, the actual model, the live/proxy/cache origin, and the
    attempt + measurement timestamp."""
    response = run.raw_response if isinstance(run.raw_response, dict) else {}
    measured_at = response.get("measured_at")
    if not isinstance(measured_at, str) or not measured_at:
        measured_at = _isoformat(run.completed_at)
    return {
        "run_id": run.id,
        "prompt_template": run.prompt_template,
        "prompt": run.prompt,
        "status": run.status,
        "score": round(float(run.score), 2) if run.score is not None else None,
        "model": response.get("model"),
        "engine_source": response.get("engine_source"),
        "served_from_cache": bool(response.get("served_from_cache")),
        "attempt": response.get("attempt"),
        "measured_at": measured_at,
        # SIGV2-1313: SIGV2-1300 records why a run did not reach its named
        # engine, and until now that only existed in the database. SIGV2-1299
        # marks a fallback cell in the UI but cannot say which of the four
        # reasons it was. `fallback_error` is deliberately not serialised: it
        # carries a provider error string for an operator, not customer copy.
        "fallback_reason": response.get("fallback_reason"),
    }


def _serialize_batch_evidence(batch: models.VisibilityRunBatch) -> dict[str, Any]:
    runs = [_serialize_run_evidence(run) for run in (batch.runs or [])]
    return {
        "batch_id": batch.id,
        "audit_job_id": batch.audit_job_id,
        "schedule_key": batch.schedule_key,
        "measurement_origin": _batch_measurement_origin(batch),
        "run_ids": [entry["run_id"] for entry in runs],
        "runs": runs,
    }


@lru_cache(maxsize=512)
def _brand_pattern(normalized_brand: str) -> re.Pattern[str]:
    """Word-boundary matcher for a brand name, cached per brand."""
    return re.compile(rf"(?<![\w-]){re.escape(normalized_brand)}(?![\w-])")


def _brand_named_in_batch(batch: models.VisibilityRunBatch, brand_name: str | None) -> bool:
    """Whether any answer in this batch names the brand in its body text.

    Scoring only ever looked for the *domain* in the answer text, and the
    brand string was never passed in, so being recommended by name without a
    link measured the same as not appearing at all. "Recommended, not linked"
    is the normal shape of an AI answer and the signal customers track, so it
    gets its own presence state.

    This is a reported state only: the 0-100 composite is untouched, so no
    existing score or trend line moves (Razvan, 9 Oct). Matched on a word
    boundary and only for names of three characters or more, because a loose
    substring match on a short name would report a mention in any answer that
    happened to contain those letters.
    """
    normalized_brand = str(brand_name or "").strip().lower()
    if len(normalized_brand) < 3:
        return False
    # Compiled once per brand rather than once per cell: this runs for every
    # prompt/engine pair on a project, so a summary for 50 prompts across
    # four engines would otherwise rebuild the same pattern 200 times.
    pattern = _brand_pattern(normalized_brand)
    for run in batch.runs or []:
        response = run.raw_response if isinstance(run.raw_response, dict) else {}
        answer = response.get("answer")
        if isinstance(answer, str) and pattern.search(answer.lower()):
            return True
    return False


def _run_answered(run: models.VisibilityRun) -> bool:
    """Whether one run carries an actual answer from the engine.

    A status of ``succeeded`` is not enough. A live reasoning engine can be
    billed in full and still return nothing (SIGV2-1269): the run is written
    ``succeeded`` because the HTTP call worked, the score comes out 0 because
    no text mentioned the brand, and the surface then reports a measured zero
    for an answer the engine never gave. Six such rows on the preprod project
    are what made "Why AI recommends your website" read 0 on every card while
    labelling them Measured.

    Citations alone also count: an engine may return sources with no prose,
    and that is still an answer about where the brand appears.

    Emptiness has to be *stated* to count. A run with no ``raw_response`` at
    all is unknown, not empty, and keeps its existing meaning: the worker
    always writes a response on success, so a missing one is an old or
    synthetic row, and reading it as a non-measurement would silently rewrite
    the score of every historical cell shaped that way. Only a response that
    is present and carries no answer is rejected, which is exactly the shape
    the live reasoning engine produced: ``{"answer": "", "usage": {...}}``.
    """
    if run.status != "succeeded":
        return False
    if run.valid_citations:
        return True
    if not isinstance(run.raw_response, dict):
        return True
    answer_keys = ("answer", "answer_excerpt", "text")
    present = [key for key in answer_keys if key in run.raw_response]
    if not present:
        return True
    return any(
        isinstance(run.raw_response.get(key), str) and run.raw_response[key].strip()
        for key in present
    )


def _batch_measured_nothing(batch: models.VisibilityRunBatch) -> bool:
    """Whether a batch has runs and not one of them produced an answer.

    A batch is only evidence of absence if something actually answered. Until
    the writer was corrected, an exhausted retry chain was stored as
    ``degraded`` with ``score=0.0``, which every reader then counted as a
    completed measurement of zero visibility. Those rows are still in the
    database, so the check is made here as well as at write time.

    It also covers the run that succeeded and said nothing, which is the same
    false zero arriving by a different route and was not caught by the first
    version of this check: the batch status was ``succeeded``, so it sailed
    through as a real measurement.

    A batch with no run rows at all is left alone: that is a batch whose runs
    were not loaded or never created, which is not the same claim.
    """
    runs = list(batch.runs or [])
    if not runs:
        return False
    return not any(_run_answered(run) for run in runs)


def _citation_host(citation: str) -> str | None:
    return _normalize_target_domain(citation)


def _cell_engine_identity(
    batch: models.VisibilityRunBatch | None,
) -> tuple[str | None, str | None, bool]:
    """Collapse per-run provenance to cell-level (engine_source, model,
    live_measured). Mixed sources across a batch's template runs surface as
    "mixed" rather than silently picking one."""
    if batch is None:
        return None, None, False
    sources: set[str] = set()
    models_seen: set[str] = set()
    live = False
    for run in batch.runs or []:
        if run.status != "succeeded" or not isinstance(run.raw_response, dict):
            continue
        source = run.raw_response.get("engine_source")
        model = run.raw_response.get("model")
        if source:
            sources.add(str(source))
            if source == "openrouter_live":
                live = True
        if model:
            models_seen.add(str(model))
    engine_source = sorted(sources)[0] if len(sources) == 1 else ("mixed" if sources else None)
    model = sorted(models_seen)[0] if len(models_seen) == 1 else ("mixed" if models_seen else None)
    return engine_source, model, live


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _ordered_providers(values: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    """Normalize a provider list to the canonical order of OFFERED engines.

    This is the chokepoint for the SIGV2-1215 withdrawal. Entitlement rosters,
    prompt listings, per-engine breakdowns, trend series and the measurement
    enumeration all pass through here, so a withdrawn engine cannot reach a
    customer surface even from a prompt row that still names it. The stored row
    is left alone: this drops the engine from what is shown and measured, not
    from the customer's data.
    """
    normalized = {str(value).strip().lower() for value in values if str(value).strip()}
    return [provider for provider in offered_visibility_providers() if provider in normalized]


def _measured_by_plan(
    values: list[str] | tuple[str, ...] | set[str],
    *,
    plan_providers: list[str] | None,
) -> list[str]:
    """``_ordered_providers``, narrowed to the engines a plan measures.

    The plan-scoped half of the same chokepoint (SIGV2-1216). ``_ordered_providers``
    answers "does the product offer this engine"; this answers "does this
    project's plan measure it", which is the question every surface that
    reports a measurement actually needs.

    It exists because a roster can shrink. Moving Gemini off the Specialist
    roster stops the sweep from measuring it, but the per-engine breakdown, the
    project score, the trend series, Share of Voice and the per-search-type
    scores are all derived from the stored prompt rows, so without this they
    would keep reporting the last cell Gemini ever recorded, frozen, on exactly
    the customers who had selected it. That is the SIGV2-1215 defect one plan
    down, and the answer is the same: an engine nobody re-measures gets no row
    and no place in an aggregate.

    History is filtered by the *current* roster rather than cut at the date the
    roster changed, so every point in a series is computed over the same set of
    engines. The level moves once; the line never shows a step that reads as a
    drop in performance.

    ``plan_providers=None`` means "no plan in scope", and leaves the list at
    what the product offers. Nothing customer-facing should pass ``None``: it
    is for the caller that genuinely has no project, so a missing plan can
    never silently empty a roster.
    """
    ordered = _ordered_providers(values)
    if plan_providers is None:
        return ordered
    measured = set(plan_providers)
    return [provider for provider in ordered if provider in measured]


def _normalize_target_domain(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    try:
        parsed = urlparse(normalized if "://" in normalized else f"https://{normalized}")
        hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    except Exception:
        hostname = normalized.rstrip(".")
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname or None


def _context_matches_domain(context_key: str | None, domain: str | None) -> bool:
    normalized_context = str(context_key or "").strip().lower()
    normalized_domain = _normalize_target_domain(domain)
    if not normalized_context or not normalized_domain:
        return False
    return normalized_context == normalized_domain or normalized_context.startswith(
        f"{normalized_domain}/"
    )


def _batches_last_measured_at(
    batches: list[models.VisibilityRunBatch],
) -> datetime | None:
    """When the freshest of these batches was measured (SIGV2-1208).

    ``completed_at`` is the measurement time; ``created_at`` is the fallback
    for a batch that never recorded one, which is the honest direction: a row
    the aggregate already counts must contribute its age, not vanish from it.
    ``None`` means nothing has been measured, which is not the same as "now".
    """
    timestamps = [
        batch.completed_at or batch.created_at
        for batch in batches
        if (batch.completed_at or batch.created_at) is not None
    ]
    if not timestamps:
        return None
    return max(
        timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
        for timestamp in timestamps
    )


def _count_target_citations(batch: models.VisibilityRunBatch) -> int:
    """Count valid citations that belong to the batch's target domain.

    Runs store every valid citation found in the provider response, so an
    unfiltered count would credit the target with citations of other domains.
    """
    total = 0
    for run in batch.runs or []:
        for citation in run.valid_citations or []:
            if batch.target_domain:
                if matches_target_domain(citation, batch.target_domain):
                    total += 1
            else:
                total += 1
    return total


class ProjectVisibilityService:
    def __init__(self, db: Session):
        self.db = db
        # One roster lookup per project for the life of this service, which is
        # request-scoped (SIGV2-1216). ``serialize_query`` needs the project's
        # roster and is called once per prompt row, so without the memo the
        # prompt listing would re-resolve the same plan for every row.
        self._measured_providers_by_project_id: dict[int, list[str]] = {}

    def resolve_plan(self, project: models.Project) -> str:
        """The plan id whose measurement policy applies to this project."""
        owner = project.workspace.owner if project.workspace else None
        subscription_plan = resolve_plan_alias(resolve_entitled_subscription_plan(owner))
        trial_plan = resolve_plan_alias(getattr(owner, "trial_plan", None))
        return subscription_plan or trial_plan or "plan_starter"

    def measured_providers(self, project: models.Project) -> list[str]:
        """The engines this project's plan measures, in canonical order.

        The authority for every surface that reports a measurement
        (SIGV2-1216). It is the plan's roster, so it answers the question the
        sweep already answers the same way: an engine outside it is not being
        re-measured, whatever a stored prompt row still names.
        """
        providers = plan_allowed_providers(self.resolve_plan(project))
        if project.id is not None:
            self._measured_providers_by_project_id[int(project.id)] = providers
        return providers

    def _measured_providers_for_project_id(self, project_id: int | None) -> list[str] | None:
        """``measured_providers`` from a project id, memoised.

        ``None`` only when the project cannot be resolved at all, which keeps a
        lookup failure from reading as "this plan measures nothing" and
        emptying a roster that should be full.
        """
        if project_id is None:
            return None
        cached = self._measured_providers_by_project_id.get(int(project_id))
        if cached is not None:
            return cached
        project = self.db.query(models.Project).filter(models.Project.id == int(project_id)).first()
        if project is None:
            return None
        return self.measured_providers(project)

    def resolve_entitlements(self, project: models.Project) -> dict[str, Any]:
        plan = self.resolve_plan(project)
        config = visibility_plan_config(plan)
        allowed_providers = _ordered_providers(config.get("allowed_providers", []))
        # A refusal must be able to name the cap and the plan that raises it,
        # so both travel with the entitlement instead of being restated by the
        # client (SIGV2-1142).
        upgrade = next_plan_with_more_queries(plan)
        return {
            "plan": plan,
            "plan_label": plan_display_name(plan),
            "upgrade_plan": upgrade[0] if upgrade else None,
            "upgrade_plan_label": plan_display_name(upgrade[0]) if upgrade else None,
            "upgrade_max_queries": upgrade[1] if upgrade else None,
            "max_queries": int(config.get("max_queries", 0)),
            "allowed_providers": allowed_providers,
            # SIGV2-1188: how often the scheduled sweep re-measures this
            # project, so a surface can state the cadence honestly instead of
            # implying the (now plan-specific) hourly default.
            "sweep_interval_seconds": plan_sweep_interval_seconds(plan),
            "measurement_cadence": plan_measurement_cadence(plan),
            "engines": self.build_engine_roster(project),
            "is_locked": int(config.get("max_queries", 0)) <= 0,
            "estimated_cost_per_check": {
                provider: calculate_audit_credit_cost(
                    provider=provider,
                    tier="lite",
                    category="visibility_check",
                )
                for provider in allowed_providers
            },
        }

    def build_engine_roster(self, project: models.Project) -> list[dict[str, Any]]:
        """Public-safe per-engine roster and measurement status.

        Each engine reports its label, whether live (OpenRouter) measurement is
        available, the measurement source in effect, and the freshest completed
        run timestamp for this project. API-model answers are not guaranteed
        identical to consumer chat apps with browsing or personalisation.

        Withdrawn engines are absent (SIGV2-1215): a roster card is a claim
        that the engine is measured, so it can only list engines the product
        offers. Their recorded runs are untouched, just unlisted.

        SIGV2-1216 added ``measured_on_plan``, because offering an engine and
        measuring it for this project are two different facts and this payload
        was only carrying the first. The two were the same fact until a plan
        roster shrank.

        SIGV2-1228 is the other half: the listing was the product's whole
        offered set on every plan, so Starter was shown seven engines while its
        roster measures one. A card is a claim that the engine is measured, and
        six of those seven claims were false. The list stays, because it is the
        only place a customer can see what the product covers, and a plan-gated
        surface should say what unlocks it rather than disappear (SIGV2-1221),
        so an unmeasured row now also carries ``plan_unavailable_reason`` and
        the cheapest purchasable plan that does measure the engine.

        An unmeasured row carries no number and no timestamp. SIGV2-1216 kept
        ``last_measured_at`` on the grounds that it is a true statement about
        the project's history; this ticket suppresses it, because the project
        may hold real runs for an engine from a richer plan or a one-off
        on-demand check, and a date printed beside a row nothing is
        re-measuring reads as a current measurement. That is the same false
        claim SIGV2-1215 removed, so the honest row is the empty one plus the
        reason it is empty. The history itself is untouched in the database and
        still reachable from every surface that reports measurements the plan
        does take.
        """
        freshness_rows = (
            self.db.query(
                models.VisibilityRun.provider,
                func.max(models.VisibilityRun.completed_at),
            )
            .join(
                models.VisibilityRunBatch,
                models.VisibilityRun.batch_id == models.VisibilityRunBatch.id,
            )
            .filter(
                models.VisibilityRunBatch.project_id == project.id,
                models.VisibilityRun.completed_at.isnot(None),
            )
            .group_by(models.VisibilityRun.provider)
            .all()
        )
        last_measured = {
            str(provider).strip().lower(): _isoformat(completed_at)
            for provider, completed_at in freshness_rows
        }

        plan = self.resolve_plan(project)
        measured = set(self.measured_providers(project))

        roster: list[dict[str, Any]] = []
        for provider in offered_visibility_providers():
            live_capable = provider in LIVE_MEASURABLE_PROVIDERS
            measured_on_plan = provider in measured
            unlocks_on_plan = (
                None if measured_on_plan else next_plan_measuring_provider(plan, provider)
            )
            roster.append(
                {
                    "provider": provider,
                    "label": VISIBILITY_PROVIDER_LABELS.get(provider, provider.title()),
                    "live_measurement": "available" if live_capable else "unavailable",
                    "live_unavailable_reason": (
                        None if live_capable else LIVE_UNAVAILABLE_REASONS.get(provider)
                    ),
                    "measurement_source": "openrouter_live" if live_capable else "bedrock_proxy",
                    # Suppressed, not flagged, on a row this plan does not
                    # measure (SIGV2-1228): the recorded run is real, but
                    # printing its date next to an unmeasured engine claims a
                    # live measurement.
                    "last_measured_at": (last_measured.get(provider) if measured_on_plan else None),
                    # Whether this project's plan measures the engine, as
                    # opposed to whether the product offers it. The two were
                    # the same fact until a plan roster shrank (SIGV2-1216).
                    "measured_on_plan": measured_on_plan,
                    "plan_unavailable_reason": (
                        None if measured_on_plan else REASON_NOT_MEASURED_ON_PLAN
                    ),
                    "unlocks_on_plan": unlocks_on_plan,
                    "unlocks_on_plan_label": (
                        plan_display_name(unlocks_on_plan) if unlocks_on_plan else None
                    ),
                }
            )
        return roster

    def list_queries(
        self,
        *,
        project_id: int,
        include_inactive: bool = False,
    ) -> list[models.ProjectVisibilityQuery]:
        query = (
            self.db.query(models.ProjectVisibilityQuery)
            .filter(models.ProjectVisibilityQuery.project_id == project_id)
            .order_by(
                models.ProjectVisibilityQuery.created_at.asc(),
                models.ProjectVisibilityQuery.id.asc(),
            )
        )
        if not include_inactive:
            query = query.filter(models.ProjectVisibilityQuery.is_active.is_(True))
        return query.all()

    def measured_query_ids(self, *, project: models.Project) -> set[int]:
        """The active prompts the plan cap still schedules, by id.

        SIGV2-1188: a downgrade shrinks the cap but never deletes prompts or
        their history. Active prompts past the cap simply stop being measured;
        this is the same "first N active, in creation order" set the sweep
        uses, so the surface can mark exactly the rows the plan no longer
        covers.
        """
        entitlements = self.resolve_entitlements(project)
        allowed = max(int(entitlements["max_queries"]), 0)
        active = self.list_queries(project_id=project.id, include_inactive=False)
        return {query.id for query in active[:allowed]}

    def get_query(self, *, project_id: int, query_id: int) -> models.ProjectVisibilityQuery:
        visibility_query = (
            self.db.query(models.ProjectVisibilityQuery)
            .filter(
                models.ProjectVisibilityQuery.id == query_id,
                models.ProjectVisibilityQuery.project_id == project_id,
            )
            .first()
        )
        if visibility_query is None:
            raise HTTPException(status_code=404, detail="Visibility query not found")
        return visibility_query

    def create_query(
        self,
        *,
        project: models.Project,
        query_text: str,
        query_type: str,
        providers: list[str],
        search_type: str | None = None,
        origin: str = ORIGIN_CUSTOMER,
    ) -> models.ProjectVisibilityQuery:
        entitlements = self.resolve_entitlements(project)
        normalized_query_text = self._normalize_query_text(query_text)
        normalized_query_type = self._normalize_query_type(query_type)
        normalized_providers = self._normalize_providers(
            providers,
            allowed_providers=entitlements["allowed_providers"],
        )
        # SIGV2-1186: the search type is stored at creation, not inferred later.
        # A caller that sends one has it honoured; a caller that sends nothing
        # (a free-form prompt the customer typed) gets the text-based suggestion
        # written down, so the type is always an explicit property of the row
        # and the customer can see and change it.
        resolved_search_type = self._normalize_search_type(
            search_type,
            query_text=normalized_query_text,
        )

        # SIGV2-1197: matched case-insensitively, exactly as the edit path
        # matches. Until this ticket creation compared the raw strings, so a
        # project could hold "Best payroll software" and "best payroll
        # software" side by side: one question asked twice, measured twice and
        # charged twice. An inactive match is still reactivated and overwritten
        # rather than refused, which is deliberate and useful; only the
        # comparison changed.
        existing = (
            self.db.query(models.ProjectVisibilityQuery)
            .filter(
                models.ProjectVisibilityQuery.project_id == project.id,
                func.lower(models.ProjectVisibilityQuery.query_text)
                == normalized_query_text.lower(),
            )
            .first()
        )
        if existing is not None:
            if existing.is_active:
                raise HTTPException(
                    status_code=409, detail="Visibility query already exists for this project"
                )
            self._enforce_query_limit(
                project_id=project.id,
                max_queries=entitlements["max_queries"],
                current_query_id=existing.id,
                plan=entitlements["plan"],
            )
            existing.query_type = normalized_query_type
            existing.search_type = resolved_search_type
            existing.origin = self._normalize_origin(origin)
            existing.providers = normalized_providers
            existing.is_active = True
            self.db.commit()
            self.db.refresh(existing)
            self.request_visibility_refresh(project)
            return existing

        self._enforce_query_limit(
            project_id=project.id,
            max_queries=entitlements["max_queries"],
            plan=entitlements["plan"],
        )

        visibility_query = models.ProjectVisibilityQuery(
            project_id=project.id,
            query_text=normalized_query_text,
            query_type=normalized_query_type,
            search_type=resolved_search_type,
            origin=self._normalize_origin(origin),
            providers=normalized_providers,
            is_active=True,
        )
        self.db.add(visibility_query)
        self.db.commit()
        self.db.refresh(visibility_query)
        self.request_visibility_refresh(project)
        return visibility_query

    def request_visibility_refresh(self, project: models.Project) -> VisibilityRefreshResult:
        """Measure this project's prompts now rather than at the next sweep.

        Before SIGV2-1182 adding a prompt enqueued nothing: the visibility
        worker's hourly project loop was the only producer, so the prompt the
        customer had just added went unmeasured for up to
        ``VISIBILITY_SCHEDULE_SECONDS`` and every surface said "No prompt data
        yet" in the meantime.

        One refresh per project, coalesced and idempotent (the lease in
        ``services.visibility_refresh_service``), and never billed to the
        customer: Signal started it, not the customer's scan. The refresh job
        names only the project, so the worker enumerates the active prompts when
        it starts and a prompt added while the job was still queued is measured
        by the same run.

        Never raises: a prompt the customer saved is not lost because Redis is
        unreachable.
        """
        if not self.list_queries(project_id=project.id, include_inactive=False):
            return VisibilityRefreshResult(reason="no_active_prompts")
        return enqueue_project_visibility_refresh(project_id=project.id)

    def update_query(
        self,
        *,
        project: models.Project,
        query_id: int,
        is_active: bool | None,
        providers: list[str] | None,
        query_type: str | None,
        search_type: str | None = None,
        query_text: str | None = None,
    ) -> models.ProjectVisibilityQuery:
        """Apply a partial edit to one tracked prompt.

        SIGV2-1194 added ``query_text``: until then the wording was immutable
        once saved, so a customer who wanted to refine a prompt had to delete it
        and lose its history. An edit applies to the whole project and to future
        scans; the measurements already recorded keep the wording they were
        taken under. Every other field behaves exactly as before.
        """
        entitlements = self.resolve_entitlements(project)
        visibility_query = self.get_query(project_id=project.id, query_id=query_id)

        next_is_active = visibility_query.is_active if is_active is None else bool(is_active)
        if next_is_active:
            self._enforce_query_limit(
                project_id=project.id,
                max_queries=entitlements["max_queries"],
                current_query_id=visibility_query.id,
                plan=entitlements["plan"],
            )

        # Gaining an engine creates prompt/engine cells that have never been
        # measured, which is the same situation as a new prompt and needs the
        # same refresh. Until this, a provider edit enqueued nothing: the row
        # named a live engine immediately and stayed blank until the plan's
        # cadence came round, up to two days on Specialist and a week on
        # Starter. That is indistinguishable from the edit having failed, and
        # it is the repair path for a prompt stranded on an engine its plan
        # stopped measuring, so the repair has to actually measure.
        # Losing an engine needs nothing new measured.
        providers_gained = False
        if providers is not None:
            previous_providers = set(_ordered_providers(list(visibility_query.providers or [])))
            visibility_query.providers = self._normalize_providers(
                providers,
                allowed_providers=entitlements["allowed_providers"],
            )
            providers_gained = bool(set(visibility_query.providers) - previous_providers)

        if query_type is not None:
            visibility_query.query_type = self._normalize_query_type(query_type)

        # SIGV2-1194: the wording itself is editable, and an edit made during
        # scan setup applies to the whole project. Normalised exactly as
        # creation normalises it, and refused for the same reasons, so an edit
        # cannot land a row creation would have rejected.
        query_text_changed = False
        if query_text is not None:
            normalized_query_text = self._normalize_query_text(query_text)
            if normalized_query_text != visibility_query.query_text:
                self._enforce_unique_query_text(
                    project_id=project.id,
                    query_text=normalized_query_text,
                    current_query_id=visibility_query.id,
                )
                # A type must never be left describing wording that no longer
                # exists, so new words always get a freshly resolved type.
                #
                # SIGV2-1194 gated this on ``search_type_source`` reporting
                # ``inferred``, to protect a type the customer had chosen. That
                # condition was almost never true and the protection was
                # imaginary: since SIGV2-1186 the create path *stores* the
                # suggestion whenever the caller omits ``search_type``, so a
                # prompt nobody picked a type for still reads ``stored``.
                # SIGV2-1197 then removed every customer-facing control for
                # choosing a search type, on the add modal and on the
                # management surface alike, so no stored type represents a
                # customer's choice any more and Signal owns the assignment.
                # Do not restore the condition as a safety check: it would
                # reinstate exactly the stale-type defect it was meant to stop.
                #
                # An explicit ``search_type`` sent in the same request still
                # wins, applied below, which is how a caller stays deliberate.
                visibility_query.search_type = suggest_search_type(normalized_query_text)
                # SIGV2-1197: wording the customer rewrote is no longer
                # Signal's, so a ``generated`` row stops claiming it is. The
                # management surface badges the set as the untouched starter
                # set or as the customer's own from exactly this field. Only a
                # real text change transfers ownership: an update that leaves
                # the wording identical, or that touches only providers,
                # ``is_active`` or ``search_type``, is inside this branch's
                # guard and never reaches here.
                visibility_query.origin = ORIGIN_CUSTOMER
                visibility_query.query_text = normalized_query_text
                query_text_changed = True

        if search_type is not None:
            # SIGV2-1186: the customer retyping a prompt is the whole remedy for
            # "how does this prompt map to the type you scored it under". An
            # unrecognised value is refused rather than silently ignored: a
            # retype that appears to succeed and changes nothing is worse than
            # an error.
            visibility_query.search_type = self._require_search_type(search_type)

        # Reactivation puts a prompt back in the measured set, and the create
        # path already refreshes when it reactivates a duplicate. Doing it
        # here too means the two routes back to "active" behave the same.
        reactivated = next_is_active and not visibility_query.is_active
        visibility_query.is_active = next_is_active
        self.db.commit()
        self.db.refresh(visibility_query)
        if query_text_changed or providers_gained or reactivated:
            # New wording is a new question, so it needs its own measurement.
            # The runs recorded against the old wording are evidence for the
            # old question and are deliberately left alone: the approved design
            # states an edit applies to future scans and previous results stay
            # unchanged. Same project-scoped refresh adding a prompt uses
            # (SIGV2-1182), coalesced and never billed to the customer.
            self.request_visibility_refresh(project)
        return visibility_query

    def delete_query(self, *, project_id: int, query_id: int) -> None:
        visibility_query = self.get_query(project_id=project_id, query_id=query_id)
        self.db.delete(visibility_query)
        self.db.commit()

    def serialize_query(
        self,
        visibility_query: models.ProjectVisibilityQuery,
        *,
        plan_providers: list[str] | None = None,
    ) -> dict[str, Any]:
        """A prompt row as a surface may read it.

        ``plan_providers`` is the project's roster, resolved from the prompt's
        own project when not supplied, so no caller can forget it and serve a
        prompt that claims an engine its plan stopped measuring (SIGV2-1216).
        ``build_summary`` passes the roster it already holds; the single-prompt
        router paths let it resolve itself.
        """
        stored_search_type = getattr(visibility_query, "search_type", None)
        if plan_providers is None:
            plan_providers = self._measured_providers_for_project_id(
                getattr(visibility_query, "project_id", None)
            )
        return {
            "id": visibility_query.id,
            "project_id": visibility_query.project_id,
            "query_text": visibility_query.query_text,
            "query_type": visibility_query.query_type,
            # Canonical five-way search type (Brand/Category/Problem/Feature/
            # Comparison). Serialised alongside the internal aeo/geo lane, which
            # stays untouched for its existing consumers (SIGV2-1010 AC3).
            #
            # SIGV2-1186: this is now the prompt's stored type whenever it has
            # one. Until this ticket it was re-derived from the prompt text on
            # every read, so the product reported a type the customer had never
            # chosen and could not explain. A prompt written before the column
            # existed still has no stored type, so it keeps the old inferred
            # answer and ``search_type_source`` says which of the two it is.
            "search_type": resolve_search_type(
                stored=stored_search_type,
                raw_query=visibility_query.query_text,
            ),
            "search_type_source": search_type_source(stored_search_type),
            # What the text classifier would suggest, so a surface can offer a
            # correction without re-implementing the taxonomy client-side.
            "search_type_suggested": suggest_search_type(visibility_query.query_text),
            # SIGV2-1186: generated prompts have to be tellable from the
            # customer's own. NULL (every pre-existing row) reads as theirs.
            "origin": self._normalize_origin(getattr(visibility_query, "origin", None)),
            "is_generated": self._normalize_origin(getattr(visibility_query, "origin", None))
            == ORIGIN_GENERATED,
            "providers": _measured_by_plan(
                list(visibility_query.providers or []), plan_providers=plan_providers
            ),
            # Engines the row names that the current plan roster does not
            # measure. A roster change (SIGV2-1216) can leave a prompt pinned
            # to an engine the plan stopped measuring, and without this field
            # the row reads as a live prompt that silently never updates.
            # Withdrawn engines are not reported here: they are not "outside
            # the plan", they are gone from the product (SIGV2-1215).
            "unmeasured_providers": [
                provider
                for provider in _ordered_providers(list(visibility_query.providers or []))
                if plan_providers is not None and provider not in plan_providers
            ],
            "is_active": bool(visibility_query.is_active),
            "created_at": _isoformat(visibility_query.created_at),
            "updated_at": _isoformat(visibility_query.updated_at),
        }

    def build_summary(
        self,
        *,
        project: models.Project,
        include_inactive: bool = False,
        audit_job_id: str | None = None,
    ) -> dict[str, Any]:
        self.bridge_legacy_tracker_entries(project=project)
        entitlements = self.resolve_entitlements(project)
        queries = self.list_queries(project_id=project.id, include_inactive=include_inactive)
        active_queries = [query for query in queries if query.is_active]
        latest_batches = self._latest_batches_for_queries(
            project_id=project.id,
            queries=active_queries,
            target_domain=self._project_primary_domain(project),
            audit_job_id=audit_job_id,
        )
        competitor_domains = {entry["domain"] for entry in self._competitor_domains(project)}

        # SIGV2-1216: the plan's roster, not the stored rows, decides which
        # engines this snapshot reports. A prompt written while the plan still
        # measured an engine keeps naming it, so without this the breakdown and
        # every aggregate below would keep counting the last cell that engine
        # ever recorded - a frozen 90 averaging with a live 10 and reporting 50.
        plan_providers = list(entitlements["allowed_providers"])
        providers_in_scope = _measured_by_plan(
            {provider for query in active_queries for provider in list(query.providers or [])},
            plan_providers=plan_providers,
        )
        if not providers_in_scope:
            providers_in_scope = list(plan_providers)

        provider_breakdown: dict[str, dict[str, Any]] = {
            provider: {
                "provider": provider,
                "tracked_queries": 0,
                "completed_checks": 0,
                "cited_checks": 0,
                "visibility_score": None,
            }
            for provider in providers_in_scope
        }

        query_rows: list[dict[str, Any]] = []
        completed_checks = 0
        cited_checks = 0
        pending_checks = 0
        last_updated_at: datetime | None = None
        all_batch_scores: list[float] = []
        all_breakdowns: list[dict[str, float]] = []
        provider_batch_scores: dict[str, list[float]] = defaultdict(list)

        target_domain = self._project_primary_domain(project)
        for query in active_queries:
            query_providers = _measured_by_plan(
                list(query.providers or []), plan_providers=plan_providers
            )
            row_results: list[dict[str, Any]] = []
            row_batches: list[models.VisibilityRunBatch] = []
            row_scores: list[float] = []
            row_last_checked_at: datetime | None = None

            for provider in query_providers:
                batch = latest_batches.get((query.query_text, provider))
                if batch is not None:
                    row_batches.append(batch)
                cell = self._serialize_batch_result(
                    provider=provider, batch=batch, brand_name=project.name
                )
                row_results.append(cell)

                provider_row = provider_breakdown.setdefault(
                    provider,
                    {
                        "provider": provider,
                        "tracked_queries": 0,
                        "completed_checks": 0,
                        "cited_checks": 0,
                        "visibility_score": None,
                    },
                )
                provider_row["tracked_queries"] += 1

                # A failed check is not a completed one. Counting it as
                # completed made the coverage denominator claim measurements
                # that never happened, and since the per-search-type path
                # already excludes failed cells, the same project reported two
                # different coverages depending on which surface asked.
                if cell["status"] == "pending":
                    pending_checks += 1
                elif cell["status"] != "failed":
                    completed_checks += 1
                    provider_row["completed_checks"] += 1
                    if cell["status"] == "cited":
                        cited_checks += 1
                        provider_row["cited_checks"] += 1

                if isinstance(cell["score"], (int, float)):
                    row_scores.append(float(cell["score"]))
                    all_batch_scores.append(float(cell["score"]))
                    provider_batch_scores[provider].append(float(cell["score"]))
                if cell.get("score_breakdown"):
                    all_breakdowns.append(cell["score_breakdown"])

                # A failed attempt must not advance the freshness clock. It
                # has a timestamp, so without this guard the surface said the
                # data was measured moments ago while carrying nothing new:
                # the customer reads the failure as fresh. The attempt time is
                # still on the cell and in its evidence, so nothing
                # diagnostic is lost; only the claim of freshness is dropped.
                cell_last_checked_at = (
                    None
                    if cell["status"] == "failed"
                    else self._parse_batch_datetime(cell["last_checked_at"])
                )
                if cell_last_checked_at and (
                    row_last_checked_at is None or cell_last_checked_at > row_last_checked_at
                ):
                    row_last_checked_at = cell_last_checked_at
                if cell_last_checked_at and (
                    last_updated_at is None or cell_last_checked_at > last_updated_at
                ):
                    last_updated_at = cell_last_checked_at

            average_score = round(sum(row_scores) / len(row_scores), 2) if row_scores else None
            query_rows.append(
                {
                    **self.serialize_query(query, plan_providers=plan_providers),
                    "average_score": average_score,
                    "last_checked_at": _isoformat(row_last_checked_at),
                    "results": row_results,
                    **self._build_row_table_fields(
                        row_results=row_results,
                        row_batches=row_batches,
                        competitor_domains=competitor_domains,
                        target_domain=target_domain,
                    ),
                }
            )

        for provider, row in provider_breakdown.items():
            scores = provider_batch_scores.get(provider, [])
            if scores:
                row["visibility_score"] = round(sum(scores) / len(scores), 2)
            else:
                row["visibility_score"] = None

        trend_payload = self.build_trends(project=project, days=30, bridge_legacy=False)
        points = trend_payload["points"]
        trend_delta = None
        if len(points) >= 2:
            latest = points[-1]["visibility_score"]
            previous = points[-2]["visibility_score"]
            if isinstance(latest, (int, float)) and isinstance(previous, (int, float)):
                trend_delta = round(float(latest) - float(previous), 2)

        total_checks = completed_checks + pending_checks
        visibility_score = (
            round(sum(all_batch_scores) / len(all_batch_scores), 2) if all_batch_scores else None
        )

        aggregate_breakdown = None
        if all_breakdowns:
            keys = ["citation_presence", "citation_position", "text_mention", "topic_relevance"]
            n = len(all_breakdowns)
            aggregate_breakdown = {
                k: round(sum(bd.get(k, 0.0) for bd in all_breakdowns) / n, 1) for k in keys
            }

        entitlements["used_queries"] = len(active_queries)
        entitlements["remaining_queries"] = max(
            0, int(entitlements["max_queries"]) - len(active_queries)
        )

        return {
            "project_id": project.id,
            # The scan this snapshot belongs to, or None for the default view
            # (latest measurement per query+provider across every origin).
            "audit_job_id": audit_job_id,
            "entitlements": entitlements,
            "queries_configured": len(active_queries),
            "providers": providers_in_scope,
            "visibility_score": visibility_score,
            "score_breakdown": aggregate_breakdown,
            "trend_delta": trend_delta,
            "completed_checks": completed_checks,
            "pending_checks": pending_checks,
            "cited_checks": cited_checks,
            "total_checks": total_checks,
            "last_updated_at": _isoformat(last_updated_at),
            "provider_breakdown": [provider_breakdown[provider] for provider in providers_in_scope],
            "queries": query_rows,
        }

    def build_trends(
        self, *, project: models.Project, days: int = 30, bridge_legacy: bool = True
    ) -> dict[str, Any]:
        if bridge_legacy:
            self.bridge_legacy_tracker_entries(project=project)
        entitlements = self.resolve_entitlements(project)
        active_queries = self.list_queries(project_id=project.id, include_inactive=False)
        topics = [query.query_text for query in active_queries]
        if not topics:
            return {
                "project_id": project.id,
                "days": days,
                "providers": list(entitlements["allowed_providers"]),
                "points": [],
            }

        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
        target_domain = self._project_primary_domain(project)
        batch_query = (
            self.db.query(models.VisibilityRunBatch)
            .filter(
                models.VisibilityRunBatch.project_id == project.id,
                models.VisibilityRunBatch.topic.in_(topics),
                models.VisibilityRunBatch.created_at >= cutoff,
            )
            .order_by(
                models.VisibilityRunBatch.created_at.desc(), models.VisibilityRunBatch.id.desc()
            )
        )
        if target_domain:
            batch_query = batch_query.filter(
                or_(
                    models.VisibilityRunBatch.target_domain == target_domain,
                    models.VisibilityRunBatch.target_domain.is_(None),
                )
            )
        batches = batch_query.all()

        query_map = {query.query_text: query for query in active_queries}
        daily_batches: dict[tuple[str, str, str], models.VisibilityRunBatch] = {}
        providers_in_scope: set[str] = set()

        for batch in batches:
            date_key = (
                batch.created_at.date().isoformat()
                if batch.created_at
                else datetime.now(timezone.utc).date().isoformat()
            )
            dedupe_key = (date_key, batch.topic, batch.provider)
            if dedupe_key in daily_batches:
                continue
            daily_batches[dedupe_key] = batch
            providers_in_scope.add(batch.provider)

        # SIGV2-1216: every point is computed through the plan's CURRENT
        # roster, including the historical ones. That is the deliberate choice
        # over cutting the series at the date the roster changed: a cut leaves
        # a step where an engine's cells stop, and a step in a score chart
        # reads as a drop in the customer's performance when it is only a
        # change in what is being measured. Re-reading history through the
        # current roster moves the whole line's level once instead, and leaves
        # day-over-day deltas (the ``drops_by`` alert's input) computed over
        # the same engines on both sides.
        plan_providers = list(entitlements["allowed_providers"])
        daily_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for (date_key, topic, provider), batch in daily_batches.items():
            query = query_map.get(topic)
            if query is None or provider not in _measured_by_plan(
                list(query.providers or []), plan_providers=plan_providers
            ):
                continue
            daily_rows[date_key].append(
                self._serialize_batch_result(
                    provider=provider, batch=batch, brand_name=project.name
                )
            )

        ordered_providers = (
            _measured_by_plan(providers_in_scope, plan_providers=plan_providers) or plan_providers
        )
        points: list[dict[str, Any]] = []
        for date_key in sorted(daily_rows.keys()):
            cells = daily_rows[date_key]
            completed = [cell for cell in cells if cell["status"] != "pending"]
            cited = [cell for cell in completed if cell["status"] == "cited"]
            completed_scores = [
                float(cell["score"])
                for cell in completed
                if isinstance(cell.get("score"), (int, float))
            ]

            provider_scores: dict[str, float | None] = {}
            for provider in ordered_providers:
                provider_cells = [cell for cell in completed if cell["provider"] == provider]
                provider_cell_scores = [
                    float(cell["score"])
                    for cell in provider_cells
                    if isinstance(cell.get("score"), (int, float))
                ]
                provider_scores[provider] = (
                    round(sum(provider_cell_scores) / len(provider_cell_scores), 2)
                    if provider_cell_scores
                    else None
                )

            points.append(
                {
                    "date": date_key,
                    "visibility_score": round(sum(completed_scores) / len(completed_scores), 2)
                    if completed_scores
                    else None,
                    "completed_checks": len(completed),
                    "cited_checks": len(cited),
                    "providers": provider_scores,
                }
            )

        return {
            "project_id": project.id,
            "days": days,
            "providers": ordered_providers,
            "points": points,
        }

    # ------------------------------------------------------------------
    # Comparative (brand vs competitor) visibility
    # ------------------------------------------------------------------

    def _competitor_domains(self, project: models.Project) -> list[dict[str, str]]:
        """Return competitor domains with labels from the project."""
        result = []
        for c in list(project.competitors or []):
            domain = _normalize_target_domain(str(c.normalized_domain or c.target_url or ""))
            if domain:
                result.append({"domain": domain, "label": c.display_name or domain})
        return result

    def build_comparative_summary(
        self, *, project: models.Project, days: int = 30
    ) -> dict[str, Any]:
        """Build visibility summary for primary domain AND all competitor domains.

        Every domain carries ``last_measured_at``, and the payload carries the
        plan's competitor cadence (SIGV2-1208). This is the only surface fed by
        scheduled competitor cells, and those run on a slower clock than the
        project's own domain, so a figure here can be days older than the one
        next to it. A measurement surface has to be able to say how old its
        numbers are, otherwise a stale competitor score reads as current.
        """
        plan = self.resolve_plan(project)
        competitor_interval = plan_competitor_sweep_interval_seconds(plan)
        # SIGV2-1216: the roster travels with the payload. The engine filter on
        # the comparative chart is a static list client-side, so without this
        # the tab for an engine the plan stopped measuring would survive the
        # backend filter and offer an empty view of a withdrawn measurement.
        measured_providers = self.measured_providers(project)
        primary = self._project_primary_domain(project)
        competitors = self._competitor_domains(project)
        active_queries = self.list_queries(project_id=project.id, include_inactive=False)
        topics = [q.query_text for q in active_queries]
        if not topics:
            return {
                "project_id": project.id,
                "plan": plan,
                "allowed_providers": list(measured_providers),
                "competitor_sweep_interval_seconds": competitor_interval,
                "domains": {},
            }

        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
        all_domains: list[dict[str, Any]] = []
        if primary:
            all_domains.append({"domain": primary, "label": primary, "is_primary": True})
        for c in competitors:
            if c["domain"] != primary:
                all_domains.append(
                    {"domain": c["domain"], "label": c["label"], "is_primary": False}
                )

        if not all_domains:
            return {
                "project_id": project.id,
                "plan": plan,
                "allowed_providers": list(measured_providers),
                "competitor_sweep_interval_seconds": competitor_interval,
                "domains": {},
            }

        domain_keys = [d["domain"] for d in all_domains]
        batches = (
            self.db.query(models.VisibilityRunBatch)
            .filter(
                models.VisibilityRunBatch.project_id == project.id,
                models.VisibilityRunBatch.topic.in_(topics),
                models.VisibilityRunBatch.created_at >= cutoff,
                models.VisibilityRunBatch.target_domain.in_(domain_keys),
            )
            .order_by(
                models.VisibilityRunBatch.created_at.desc(), models.VisibilityRunBatch.id.desc()
            )
            .all()
        )

        # SIGV2-1215: a withdrawn engine's recorded batches are kept but do not
        # count here. Share of Voice divides this domain's citations by every
        # domain's, so leaving Copilot's cells in would let a withdrawn engine
        # keep moving a number the customer reads.
        #
        # SIGV2-1216: the same applies to an engine this plan has stopped
        # measuring. It is the worse half of that defect, because the comparative
        # surface reads one engine at a time, so no row has to disappear for the
        # percentage to be wrong.
        measured = set(measured_providers)
        domain_batches: dict[str, list[models.VisibilityRunBatch]] = defaultdict(list)
        for batch in batches:
            if batch.target_domain and batch.provider in measured:
                domain_batches[batch.target_domain].append(batch)

        domains_result: dict[str, Any] = {}
        for d_info in all_domains:
            domain = d_info["domain"]
            d_batches = domain_batches.get(domain, [])
            provider_stats: dict[str, dict[str, Any]] = {}
            for batch in d_batches:
                prov = batch.provider
                if prov not in provider_stats:
                    provider_stats[prov] = {
                        "visibility_score": 0.0,
                        "cited_count": 0,
                        "total_checks": 0,
                        "score_sum": 0.0,
                    }
                ps = provider_stats[prov]
                ps["total_checks"] += 1
                if batch.score is not None:
                    ps["score_sum"] += float(batch.score)
                citations = _count_target_citations(batch)
                if citations > 0:
                    ps["cited_count"] += 1

            provider_final: dict[str, dict[str, Any]] = {}
            for prov, ps in provider_stats.items():
                avg_score = (
                    round(ps["score_sum"] / ps["total_checks"], 2)
                    if ps["total_checks"] > 0
                    else 0.0
                )
                provider_final[prov] = {
                    "visibility_score": avg_score,
                    "cited_count": ps["cited_count"],
                    "total_checks": ps["total_checks"],
                }

            domains_result[domain] = {
                "is_primary": d_info["is_primary"],
                "label": d_info["label"],
                "providers": provider_final,
                "last_measured_at": _isoformat(_batches_last_measured_at(d_batches)),
            }

        return {
            "project_id": project.id,
            "plan": plan,
            "allowed_providers": list(measured_providers),
            "competitor_sweep_interval_seconds": competitor_interval,
            "domains": domains_result,
        }

    def build_comparative_trends(
        self, *, project: models.Project, days: int = 90
    ) -> dict[str, Any]:
        """Build per-domain per-provider daily time series for comparative charting."""
        primary = self._project_primary_domain(project)
        competitors = self._competitor_domains(project)
        active_queries = self.list_queries(project_id=project.id, include_inactive=False)
        topics = [q.query_text for q in active_queries]
        if not topics:
            return {"project_id": project.id, "days": days, "domains": {}}

        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
        all_domains: list[dict[str, Any]] = []
        if primary:
            all_domains.append({"domain": primary, "label": primary, "is_primary": True})
        for c in competitors:
            if c["domain"] != primary:
                all_domains.append(
                    {"domain": c["domain"], "label": c["label"], "is_primary": False}
                )

        if not all_domains:
            return {"project_id": project.id, "days": days, "domains": {}}

        domain_keys = [d["domain"] for d in all_domains]
        batches = (
            self.db.query(models.VisibilityRunBatch)
            .filter(
                models.VisibilityRunBatch.project_id == project.id,
                models.VisibilityRunBatch.topic.in_(topics),
                models.VisibilityRunBatch.created_at >= cutoff,
                models.VisibilityRunBatch.target_domain.in_(domain_keys),
            )
            .order_by(models.VisibilityRunBatch.created_at.asc())
            .all()
        )

        # Group by domain → date → provider, deduplicate (keep first per day/provider)
        # SIGV2-1215: a withdrawn engine contributes no point to any series.
        # SIGV2-1216: nor does an engine this plan has stopped measuring, on
        # any day, including the days it was still being measured. See the
        # note in ``build_trends`` for why history is re-read rather than cut.
        measured = set(self.measured_providers(project))
        domain_daily: dict[str, dict[str, dict[str, float]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        seen: set[tuple[str, str, str]] = set()
        for batch in batches:
            if not batch.target_domain or batch.score is None:
                continue
            if batch.provider not in measured:
                continue
            date_key = (
                batch.created_at.date().isoformat()
                if batch.created_at
                else datetime.now(timezone.utc).date().isoformat()
            )
            dedupe = (batch.target_domain, date_key, batch.provider)
            if dedupe in seen:
                continue
            seen.add(dedupe)
            domain_daily[batch.target_domain][date_key][batch.provider] = round(
                float(batch.score), 2
            )

        domain_info_map = {d["domain"]: d for d in all_domains}
        domains_result: dict[str, Any] = {}
        for domain, daily_map in domain_daily.items():
            info = domain_info_map.get(domain, {"is_primary": False, "label": domain})
            trend_points = [
                {"date": date_key, "scores": scores}
                for date_key, scores in sorted(daily_map.items())
            ]
            domains_result[domain] = {
                "is_primary": info["is_primary"],
                "label": info["label"],
                "trend": trend_points,
            }

        # Include domains that had zero batches
        for d_info in all_domains:
            if d_info["domain"] not in domains_result:
                domains_result[d_info["domain"]] = {
                    "is_primary": d_info["is_primary"],
                    "label": d_info["label"],
                    "trend": [],
                }

        return {"project_id": project.id, "days": days, "domains": domains_result}

    def _latest_batches_for_queries(
        self,
        *,
        project_id: int,
        queries: list[models.ProjectVisibilityQuery],
        target_domain: str | None,
        audit_job_id: str | None = None,
    ) -> dict[tuple[str, str], models.VisibilityRunBatch]:
        topics = [query.query_text for query in queries]
        if not topics:
            return {}

        query = (
            self.db.query(models.VisibilityRunBatch)
            .filter(
                models.VisibilityRunBatch.project_id == project_id,
                models.VisibilityRunBatch.topic.in_(topics),
            )
            .order_by(
                models.VisibilityRunBatch.created_at.desc(), models.VisibilityRunBatch.id.desc()
            )
        )
        if target_domain:
            query = query.filter(
                or_(
                    models.VisibilityRunBatch.target_domain == target_domain,
                    models.VisibilityRunBatch.target_domain.is_(None),
                )
            )
        if audit_job_id is not None:
            # Scan-scoped view: only the batches this audit job triggered.
            # Scheduled / queued / volatility measurements stay excluded so a
            # reopened scan can never surface unrelated data (AC2).
            query = query.filter(models.VisibilityRunBatch.audit_job_id == audit_job_id)

        batches = query.all()

        latest_batches: dict[tuple[str, str], models.VisibilityRunBatch] = {}
        for batch in batches:
            key = (batch.topic, batch.provider)
            latest_batches.setdefault(key, batch)
        return latest_batches

    @staticmethod
    def _project_primary_domain(project: models.Project) -> str | None:
        return _normalize_target_domain(project.domain_url)

    def bridge_legacy_tracker_entries(
        self,
        *,
        project: models.Project,
        max_entries_per_type: int = LEGACY_BRIDGE_MAX_ENTRIES_PER_TYPE,
    ) -> dict[str, int]:
        workspace = project.workspace
        owner = workspace.owner if workspace is not None else None
        target_domain = self._project_primary_domain(project)
        if owner is None or target_domain is None:
            return {"queries_created": 0, "batches_created": 0}

        entitlements = self.resolve_entitlements(project)
        allowed_providers = _ordered_providers(entitlements.get("allowed_providers", []))
        if LEGACY_BRIDGE_PROVIDER not in allowed_providers:
            return {"queries_created": 0, "batches_created": 0}

        existing_queries = (
            self.db.query(models.ProjectVisibilityQuery)
            .filter(models.ProjectVisibilityQuery.project_id == project.id)
            .order_by(models.ProjectVisibilityQuery.id.asc())
            .all()
        )
        active_query_count = sum(1 for query in existing_queries if query.is_active)
        max_queries = int(entitlements.get("max_queries", 0))
        query_by_topic = {
            query.query_text.strip().lower(): query
            for query in existing_queries
            if query.query_text
        }

        tracker_rows: list[tuple[str, object]] = []
        aeo_rows = (
            self.db.query(models.AeoQueryTrackerEntry)
            .filter(models.AeoQueryTrackerEntry.user_id == owner.id)
            .order_by(
                models.AeoQueryTrackerEntry.tracked_at.desc(), models.AeoQueryTrackerEntry.id.desc()
            )
            .limit(max(1, int(max_entries_per_type)))
            .all()
        )
        for row in aeo_rows:
            if _context_matches_domain(row.context_key, target_domain):
                tracker_rows.append(("aeo", row))

        geo_rows = (
            self.db.query(models.GeoPromptTrackerEntry)
            .filter(models.GeoPromptTrackerEntry.user_id == owner.id)
            .order_by(
                models.GeoPromptTrackerEntry.tracked_at.desc(),
                models.GeoPromptTrackerEntry.id.desc(),
            )
            .limit(max(1, int(max_entries_per_type)))
            .all()
        )
        for row in geo_rows:
            if _context_matches_domain(row.context_key, target_domain):
                tracker_rows.append(("geo", row))

        if not tracker_rows:
            return {"queries_created": 0, "batches_created": 0}

        created_queries = 0

        for entry_type, row in tracker_rows:
            source_text = row.query if entry_type == "aeo" else row.prompt
            normalized_topic = " ".join(str(source_text or "").strip().split())
            if not normalized_topic:
                continue
            topic_key = normalized_topic.lower()

            visibility_query = query_by_topic.get(topic_key)
            if visibility_query is None:
                can_activate = max_queries > 0 and active_query_count < max_queries
                visibility_query = models.ProjectVisibilityQuery(
                    project_id=project.id,
                    query_text=normalized_topic,
                    query_type=entry_type,
                    # SIGV2-1186: a bridged row is the customer's own tracked
                    # query, so it is theirs, and its type is the text-based
                    # suggestion written down once rather than re-derived on
                    # every read. They can retype it like any other prompt.
                    search_type=suggest_search_type(normalized_topic),
                    origin=ORIGIN_CUSTOMER,
                    providers=[LEGACY_BRIDGE_PROVIDER],
                    is_active=can_activate,
                )
                self.db.add(visibility_query)
                self.db.flush()
                query_by_topic[topic_key] = visibility_query
                created_queries += 1
                if can_activate:
                    active_query_count += 1
            elif LEGACY_BRIDGE_PROVIDER not in list(visibility_query.providers or []):
                visibility_query.providers = _ordered_providers(
                    list(visibility_query.providers or []) + [LEGACY_BRIDGE_PROVIDER]
                )

        if created_queries > 0:
            self.db.commit()

        return {"queries_created": created_queries, "batches_created": 0}

    def _serialize_batch_result(
        self,
        *,
        provider: str,
        batch: models.VisibilityRunBatch | None,
        brand_name: str | None = None,
    ) -> dict[str, Any]:
        if batch is None:
            return {
                "provider": provider,
                "status": "pending",
                "batch_status": None,
                "score": None,
                "score_breakdown": None,
                "last_checked_at": None,
                "citations_found": 0,
                "presence": {
                    "state": PRESENCE_UNMEASURED,
                    "live_measured": False,
                    "reason": REASON_NO_MEASUREMENT,
                },
                "measurement_origin": None,
                "audit_job_id": None,
                "engine_source": None,
                "model": None,
                "evidence": None,
            }

        if batch.status in PENDING_BATCH_STATUSES:
            status = "pending"
        elif batch.status == "failed" or _batch_measured_nothing(batch):
            # ``_batch_measured_nothing`` heals history: batches written before
            # the writer stopped scoring total failures are stored as
            # ``degraded`` with score 0.0, and reading them as a completed
            # measurement is what turned a provider outage into a visible
            # zero. A batch whose every run failed is a failed batch whatever
            # its stored status says, and no migration is needed to say so.
            status = "failed"
        else:
            citations_found = _count_target_citations(batch)
            status = "cited" if citations_found > 0 else "not_cited"

        citations_found = _count_target_citations(batch)
        last_checked_at = batch.completed_at or batch.updated_at or batch.created_at

        aggregate_breakdown = self._compute_batch_breakdown(batch)
        engine_source, model, live_measured = _cell_engine_identity(batch)

        if status == "pending":
            presence = {
                "state": PRESENCE_UNMEASURED,
                "live_measured": False,
                "reason": REASON_MEASUREMENT_PENDING,
            }
        elif status == "failed":
            presence = {
                "state": PRESENCE_UNMEASURED,
                "live_measured": False,
                "reason": REASON_MEASUREMENT_FAILED,
            }
        elif citations_found > 0:
            presence = {
                "state": PRESENCE_DOMAIN_CITATION,
                "live_measured": live_measured,
                "reason": None,
            }
        elif (aggregate_breakdown or {}).get("text_mention", 0.0) > 0 or _brand_named_in_batch(
            batch, brand_name
        ):
            # Named in the answer without a link. Scoring only ever looked for
            # the domain string, so this read as "absent" - the same as never
            # being mentioned - on exactly the answers where the brand was
            # being recommended. The composite score is deliberately not
            # changed by this; only what the cell is called.
            presence = {
                "state": PRESENCE_BRAND_MENTION,
                "live_measured": live_measured,
                "reason": None,
            }
        else:
            # A completed measurement with no citation and no mention. Only a
            # live-engine measurement supports reading this as "not present";
            # a proxy-only measurement is explicitly not a live "no" (AC4).
            presence = {
                "state": PRESENCE_MEASURED_ABSENT,
                "live_measured": live_measured,
                "reason": (REASON_NO_EVIDENCE if live_measured else REASON_PROXY_NOT_LIVE),
            }

        return {
            "provider": provider,
            "status": status,
            "batch_status": batch.status,
            # A failed cell carries no score, whatever the row stores. Legacy
            # all-failed batches hold 0.0, and every caller that averages a
            # numeric score would otherwise pull the project mean towards a
            # number nothing measured.
            "score": (
                None if status == "failed" or batch.score is None else round(float(batch.score), 2)
            ),
            # The breakdown goes with the score. Nulling one and keeping the
            # other let a failed batch's factor numbers carry on feeding the
            # project's aggregate breakdown, which is the same defect one
            # level down: a failure contributing to a published average.
            "score_breakdown": None if status == "failed" else aggregate_breakdown,
            "last_checked_at": _isoformat(last_checked_at),
            "citations_found": citations_found,
            "presence": presence,
            "measurement_origin": _batch_measurement_origin(batch),
            "audit_job_id": batch.audit_job_id,
            "engine_source": engine_source,
            "model": model,
            "evidence": _serialize_batch_evidence(batch),
        }

    @staticmethod
    def _build_row_table_fields(
        *,
        row_results: list[dict[str, Any]],
        row_batches: list[models.VisibilityRunBatch],
        competitor_domains: set[str],
        target_domain: str | None,
    ) -> dict[str, Any]:
        """Row-level fields for the AIO prompts table (SIGV2-1010).

        - ``top_engine``: the provider whose latest measurement for this prompt
          recorded the highest score. Rule (documented, AC5): only completed
          measurements (cited / not_cited) with a numeric score are eligible;
          a tie on the top score means no defensible winner, so the value is
          null with ``tied_providers`` rather than an arbitrary pick; no
          completed measurements yields null with
          ``no_completed_measurements``. The winning cell's evidence reference
          is returned with the value.
        - ``position``: always null with a machine-readable reason. Persisted
          runs record citation order, which is explicitly NOT recommendation
          rank (AC5), and ``citation_position`` in the score breakdown is a
          scoring factor, not an ordinal answer position. No field in the
          recorded evidence supports an ordinal position, so none is invented.
        - ``who_wins``: every non-target domain cited by this prompt's
          successful runs, with its recorded citation count and the run/batch
          ids that carry the evidence. Ordering is citation frequency then
          domain name; it is NOT a recommendation rank.
        """
        eligible = [
            cell
            for cell in row_results
            if cell["status"] in {"cited", "not_cited"}
            and isinstance(cell.get("score"), (int, float))
        ]
        if not eligible:
            top_engine: dict[str, Any] = {
                "provider": None,
                "score": None,
                "reason": REASON_NO_COMPLETED_MEASUREMENTS,
                "evidence": None,
            }
        else:
            best_score = max(float(cell["score"]) for cell in eligible)
            winners = [cell for cell in eligible if float(cell["score"]) == best_score]
            if len(winners) > 1:
                top_engine = {
                    "provider": None,
                    "score": None,
                    "reason": REASON_TIED_PROVIDERS,
                    "evidence": None,
                }
            else:
                winner = winners[0]
                top_engine = {
                    "provider": winner["provider"],
                    "score": winner["score"],
                    "reason": None,
                    "evidence": winner.get("evidence"),
                }

        domain_evidence: dict[str, dict[str, Any]] = {}
        for batch in row_batches:
            for run in batch.runs or []:
                if run.status != "succeeded":
                    continue
                for citation in list(run.valid_citations or []):
                    host = _citation_host(str(citation))
                    if not host or (target_domain and host == target_domain):
                        continue
                    entry = domain_evidence.setdefault(
                        host,
                        {
                            "domain": host,
                            "is_configured_competitor": host in competitor_domains,
                            "citations": 0,
                            "run_ids": set(),
                            "batch_ids": set(),
                        },
                    )
                    entry["citations"] += 1
                    entry["run_ids"].add(run.id)
                    entry["batch_ids"].add(batch.id)

        who_wins = [
            {
                "domain": entry["domain"],
                "is_configured_competitor": entry["is_configured_competitor"],
                "citations": entry["citations"],
                "run_ids": sorted(entry["run_ids"]),
                "batch_ids": sorted(entry["batch_ids"]),
            }
            for entry in sorted(
                domain_evidence.values(),
                key=lambda entry: (-entry["citations"], entry["domain"]),
            )
        ]

        return {
            "top_engine": top_engine,
            "position": {
                "value": None,
                "reason": REASON_ORDINAL_POSITION_NOT_RECORDED,
            },
            "who_wins": who_wins,
        }

    @staticmethod
    def _compute_batch_breakdown(batch: models.VisibilityRunBatch) -> dict[str, float] | None:
        """Re-derive the per-factor score breakdown from persisted run data."""
        succeeded_runs = [
            run for run in (batch.runs or []) if run.status == "succeeded" and run.raw_response
        ]
        if not succeeded_runs:
            return None
        factors = {
            "citation_presence": 0.0,
            "citation_position": 0.0,
            "text_mention": 0.0,
            "topic_relevance": 0.0,
        }
        for run in succeeded_runs:
            result = score_response(
                batch.topic or "",
                ProjectVisibilityService._response_text(run.raw_response),
                list(run.valid_citations or []),
                target_domain=batch.target_domain,
            )
            for key in factors:
                factors[key] += result.breakdown.get(key, 0.0)
        n = len(succeeded_runs)
        return {key: round(val / n, 1) for key, val in factors.items()}

    @staticmethod
    def _response_text(raw_response: Any) -> str:
        """The answer text persisted on a run. SIGV2-1023 stores raw_response
        as a dict payload (answer + provenance); older rows may hold a plain
        string. Scoring always works on the extracted text, never the dict."""
        if isinstance(raw_response, dict):
            for key in ("answer", "text"):
                value = raw_response.get(key)
                if isinstance(value, str) and value:
                    return value
            return ""
        return raw_response if isinstance(raw_response, str) else ""

    @staticmethod
    def _normalize_query_text(query_text: str) -> str:
        normalized = " ".join(str(query_text or "").strip().split())
        if not normalized:
            raise HTTPException(status_code=422, detail="Query text is required")
        if len(normalized) > 500:
            raise HTTPException(
                status_code=422, detail="Query text must be 500 characters or fewer"
            )
        return normalized

    @staticmethod
    def _normalize_query_type(query_type: str) -> str:
        normalized = str(query_type or "aeo").strip().lower() or "aeo"
        if normalized not in SUPPORTED_VISIBILITY_QUERY_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported query type '{normalized}'",
            )
        return normalized

    @staticmethod
    def _normalize_search_type(search_type: str | None, *, query_text: str) -> str:
        """The search type to store at creation.

        An explicit canonical id is honoured. Nothing (a free-form prompt with
        no type chosen) falls back to the text-based suggestion, which is then
        *stored*: from here on the row carries its own type instead of having
        one re-derived on every read. An explicit value that is not a canonical
        id is a client error, not something to quietly replace with a guess.
        """
        if search_type is None or str(search_type).strip() == "":
            return suggest_search_type(query_text)
        return ProjectVisibilityService._require_search_type(search_type)

    @staticmethod
    def _require_search_type(search_type: str) -> str:
        normalized = normalize_search_type(search_type)
        if normalized is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unsupported search type '{search_type}'. "
                    f"Expected one of: {', '.join(CANONICAL_SEARCH_TYPES)}"
                ),
            )
        return normalized

    @staticmethod
    def _normalize_origin(origin: str | None) -> str:
        """``generated`` only when positively declared; everything else is the customer's."""
        normalized = str(origin or "").strip().lower()
        return normalized if normalized in VISIBILITY_QUERY_ORIGINS else ORIGIN_CUSTOMER

    @staticmethod
    def _parse_batch_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _normalize_providers(
        self,
        providers: list[str] | None,
        *,
        allowed_providers: list[str],
    ) -> list[str]:
        if not allowed_providers:
            raise HTTPException(
                status_code=402,
                detail="AI visibility monitoring is available on paid plans.",
            )

        requested = providers or allowed_providers[:1]
        normalized = _ordered_providers(requested)
        if not normalized:
            # SIGV2-1215: a request naming only withdrawn engines is refused by
            # name. A caller asking for Copilot alone deserves to be told the
            # engine is gone, not a generic "select at least one provider",
            # and a request that also names a live engine keeps that one
            # instead of failing whole.
            withdrawn_requested = [
                VISIBILITY_PROVIDER_LABELS.get(provider, provider)
                for provider in WITHDRAWN_VISIBILITY_PROVIDERS
                if provider in {str(value).strip().lower() for value in requested}
            ]
            if withdrawn_requested:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"{', '.join(withdrawn_requested)} is no longer measured. "
                        "Select an engine that is."
                    ),
                )
            raise HTTPException(status_code=422, detail="Select at least one provider")

        unsupported = [provider for provider in normalized if provider not in allowed_providers]
        if unsupported:
            raise HTTPException(
                status_code=402,
                detail=f"Provider access requires a higher plan: {', '.join(unsupported)}",
            )
        return normalized

    def _enforce_unique_query_text(
        self,
        *,
        project_id: int,
        query_text: str,
        current_query_id: int,
    ) -> None:
        """Refuse wording another prompt in this project already tracks.

        SIGV2-1194: editing the text must not be a way around the collision the
        create path refuses, so it fails the same way, with the same 409.
        Matched case-insensitively: two prompts differing only in capitalisation
        are the same question asked twice, and measuring both would charge the
        project twice to produce one answer.

        SIGV2-1197: inactive prompts count too. Scoping this to active rows let
        an edit land wording an inactive prompt already held, and reactivating
        that row afterwards left the project with two identical active prompts,
        the exact state both checks exist to prevent.
        """
        duplicate = (
            self.db.query(models.ProjectVisibilityQuery.id)
            .filter(
                models.ProjectVisibilityQuery.project_id == project_id,
                models.ProjectVisibilityQuery.id != current_query_id,
                func.lower(models.ProjectVisibilityQuery.query_text) == query_text.lower(),
            )
            .first()
        )
        if duplicate is not None:
            raise HTTPException(
                status_code=409, detail="Visibility query already exists for this project"
            )

    def _enforce_query_limit(
        self,
        *,
        project_id: int,
        max_queries: int,
        current_query_id: int | None = None,
        plan: str | None = None,
    ) -> None:
        if max_queries <= 0:
            raise HTTPException(
                status_code=402,
                detail="AI visibility monitoring is available on paid plans.",
            )

        query = self.db.query(models.ProjectVisibilityQuery).filter(
            models.ProjectVisibilityQuery.project_id == project_id,
            models.ProjectVisibilityQuery.is_active.is_(True),
        )
        if current_query_id is not None:
            query = query.filter(models.ProjectVisibilityQuery.id != current_query_id)

        used_queries = query.count()
        if used_queries >= max_queries:
            raise HTTPException(
                status_code=402, detail=self._limit_detail(plan, used_queries, max_queries)
            )

    @staticmethod
    def _limit_detail(plan: str | None, used_queries: int, max_queries: int) -> str:
        """Say what the cap is, what is used, what remains, and what lifts it.

        A refusal the customer cannot act on is the defect SIGV2-1142 fixes, so
        every number the caller needs is in the sentence itself. The wording is
        shared with the other tracked, per-cycle-metered resources
        (``services.plan_limit_messaging``).
        """
        return tracked_limit_detail(
            plan=plan,
            used=used_queries,
            maximum=max_queries,
            allowances=visibility_query_allowances(),
            noun_singular="prompt",
            noun_plural="prompts",
        )


def _empty_search_type_measurements() -> dict[str, dict[str, Any]]:
    # ``pending`` is the SIGV2-1182 third state: no measurement yet, but one is
    # queued or running for a prompt of this type, so the card says a run is on
    # its way instead of asserting there is no data.
    return {
        search_type: {"score": None, "answer_ratio": None, "pending": False}
        for search_type in CANONICAL_SEARCH_TYPES
    }


def compute_search_type_measurements(
    db: Session | None,
    project_id: int | None,
) -> dict[str, dict[str, Any]]:
    """Measured per-canonical-search-type visibility for a project.

    Returns a mapping covering every id in
    :data:`services.query_taxonomy.CANONICAL_SEARCH_TYPES`, each shaped
    ``{"score": float | None, "answer_ratio": {"present": int, "measured": int} | None,
    "pending": bool}``.

    Each active ``ProjectVisibilityQuery`` is classified onto a canonical search
    type via :func:`classify_query_category` + :func:`to_canonical` (the per-query
    ``query_type`` is the internal aeo/geo lane, so classification is driven off
    the query text).

    ``score`` averages the latest measured batch score per query, then averages
    those per-query means per canonical type.

    ``answer_ratio`` counts the answers themselves, which is what the approved
    ``.ft-ratio`` line asks for ("7 of 10 answers"): ``measured`` is the number of
    latest query+provider cells that completed, ``present`` the subset where the
    brand appeared. Presence is read off the same per-cell ``presence.state`` the
    dashboard's Answer Presence row uses (``_serialize_batch_result``), so the two
    cannot disagree. A type with no completed cell yields ``None`` rather than
    ``0/0``: a zero would assert we looked and found the brand in no answer
    (SIGV2-1104).

    ``pending`` is ``True`` only for a type that has at least one active prompt,
    no completed cell of its own, and a Signal-initiated refresh queued or
    running for the project (SIGV2-1182). It is what lets a surface say a run is
    on its way instead of "No prompt data yet"; a type nobody tracks keeps the
    unmeasured state, because no run is going to produce one.

    Read-only (no writes/commits) and fully defensive: missing ``db``/``project_id``,
    a missing project, no tracked queries/runs, unreachable Redis, or any
    unexpected error all resolve to all-unmeasured.
    """
    base = _empty_search_type_measurements()
    if db is None or project_id is None:
        return base

    try:
        project = db.query(models.Project).filter(models.Project.id == project_id).first()
        if project is None:
            return base

        service = ProjectVisibilityService(db)
        active_queries = service.list_queries(project_id=project_id, include_inactive=False)
        if not active_queries:
            return base

        # SIGV2-1216: the per-type score is a mean of cells, so an engine the
        # plan stopped measuring would keep contributing its last recorded
        # value to it. This is one of the aggregates, not a display.
        plan_providers = service.measured_providers(project)

        target_domain = service._project_primary_domain(project)
        latest_batches = service._latest_batches_for_queries(
            project_id=project_id,
            queries=active_queries,
            target_domain=target_domain,
        )

        per_type_scores: dict[str, list[float]] = defaultdict(list)
        per_type_measured: dict[str, int] = defaultdict(int)
        per_type_present: dict[str, int] = defaultdict(int)
        per_type_tracked: dict[str, int] = defaultdict(int)
        for visibility_query in active_queries:
            # SIGV2-1186: the prompt's stored type decides which bucket its
            # measurement lands in. The text classifier is only the fallback for
            # a prompt written before the column existed, so a customer who
            # declared a prompt to be about their buyers' problems is measured
            # under Problem even when its wording trips no pattern.
            canonical = resolve_search_type(
                stored=getattr(visibility_query, "search_type", None),
                raw_query=visibility_query.query_text,
            )
            per_type_tracked[canonical] += 1
            providers = _measured_by_plan(
                list(visibility_query.providers or []), plan_providers=plan_providers
            )
            query_scores: list[float] = []
            for provider in providers:
                batch = latest_batches.get((visibility_query.query_text, provider))
                cell = service._serialize_batch_result(
                    provider=provider, batch=batch, brand_name=project.name
                )
                state = (cell.get("presence") or {}).get("state")
                if state == PRESENCE_UNMEASURED:
                    # Missing, pending or failed: the check produced no answer,
                    # so it counts toward neither the ratio nor the mean. A
                    # failed batch carries score 0.0 (execute_batch writes it on
                    # a refused charge), and averaging that in reported a
                    # measured zero for a check that never ran.
                    continue

                per_type_measured[canonical] += 1
                if state in {PRESENCE_DOMAIN_CITATION, PRESENCE_BRAND_MENTION}:
                    per_type_present[canonical] += 1

                if batch is not None and batch.score is not None:
                    query_scores.append(float(batch.score))

            if query_scores:
                per_type_scores[canonical].append(sum(query_scores) / len(query_scores))

        for canonical, values in per_type_scores.items():
            if values:
                base[canonical]["score"] = round(sum(values) / len(values), 2)

        for canonical, measured in per_type_measured.items():
            if measured > 0:
                base[canonical]["answer_ratio"] = {
                    "present": per_type_present.get(canonical, 0),
                    "measured": measured,
                }

        # SIGV2-1182: one lease read for the project, applied only to the types
        # a queued run can actually fill. Asking Redis is skipped entirely when
        # every tracked type already has a measurement.
        awaiting = [
            canonical
            for canonical, tracked in per_type_tracked.items()
            if tracked > 0
            and base[canonical]["score"] is None
            and base[canonical]["answer_ratio"] is None
        ]
        if awaiting and visibility_refresh_in_flight(project_id):
            for canonical in awaiting:
                base[canonical]["pending"] = True
    except Exception:
        logger.exception("compute_search_type_measurements failed for project_id=%s", project_id)
        return _empty_search_type_measurements()

    return base
