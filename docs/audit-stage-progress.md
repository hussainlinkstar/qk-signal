# Audit stage progress - event-to-stage mapping (SIGV2-1021)

This documents exactly which real worker events produce each public stage
state, what happens on Redis expiry, and which stages report not-applicable.

## Public stage model

`GET /api/v1/audit/jobs/{job_id}` returns `stages`; the SSE stream at
`GET /api/v1/audit/jobs/{job_id}/events` carries the same `job_status`
payload (it serializes the polling endpoint's response), so polling and SSE
always agree on stage status, timestamps and final outcome.

| Stage id | Covers | Emitted by |
|---|---|---|
| `signal_collection` | crawl/screenshot, schema HTML fetch | `queue_worker` via `perform_audit` (`audit_runner.py`) |
| `measurement` | parallel gather: performance, network, answerability, in-audit GEO visibility check, competitor discovery | `perform_audit` after `asyncio.gather` |
| `analysis` | AI debate / single-provider analysis | debate progress events (`pipeline_started`, `layer_*`, `step_*`, `debate_finished` from `services/audit_job_event_service.py`) plus `stage_started`/`stage_completed`/`stage_failed`/`stage_skipped` around `ai_client.generate_audit` |
| `report` | scoring, report assembly, credit settlement, audit persistence | `queue_worker.handle_job` |

Stage states: `pending`, `running`, `completed`, `failed`, `skipped`,
`degraded`, `unknown`. No percent-complete is manufactured.

## Event-to-stage mapping

| Worker event (retained Redis event `type`) | Stage transition |
|---|---|
| `stage_started` + `stage` | -> `running` (bumps `attempt`; a start after a terminal state is a distinguishable retry) |
| `stage_completed` + `stage` | -> `completed`, or `degraded` when `outcome == "degraded"` |
| `stage_failed` + `stage` | -> `failed`, `reason` preserved |
| `stage_skipped` + `stage` | -> `skipped`, `reason` preserved |
| `pipeline_started`, `layer_started`, `step_started`, `step_completed`, `layer_completed` | `analysis` -> `running` |
| `debate_finished` | `analysis` -> `completed` |

All other event types are replayed verbatim on the SSE stream but do not
move a stage. `debate_finished` carries `summary`, `provider`, `model`,
`rounds`, `confidence_delta` only (existing sanitizer; no cost fields).

## Where stages report skipped / not-applicable

| Condition | Stage | Reason |
|---|---|---|
| Brand target without URL | `signal_collection` | `brand_target` (scraper/performance/network never created) |
| Scrape failed (report still produced) | `signal_collection` | `degraded` outcome, then `analysis` `skipped` with `upstream_data_unavailable` |
| No measurement task produced any result | `measurement` | `not_applicable` |
| One or more measurement tasks raised | `measurement` | `degraded`, `partial_measurement_failure`, `summary` lists the failed labels |
| `QUICK_SCAN_ENABLED` + lite/quick tier | `analysis` | `deterministic_quick_scan` |
| AI service error | `analysis` | `failed`, `ai_service_unavailable` |

There is **no answer-engine measurement stage and no competitor-comparison
stage**: SIGV2-1010 established that audits do not run a prompt/engine sweep;
`VisibilityRunBatch` rows come only from the scheduled worker. The in-audit
GEO visibility check is part of `measurement`. Skipped work is never reported
as completed.

## Failure attribution (AC4)

- An explicit `stage_failed` wins as the failed stage.
- Otherwise a failed job attributes to the **first stage still `running`**
  when the job died (`reason: job_failed`), consistent across `status`, the
  stage list and the summary.
- `degraded` is a completed-with-gaps outcome: a partial provider failure
  cannot make a valid audit look fully failed.
- Retries: `job_attempt` is attached to every stage event; a fresh
  `stage_started` after a terminal transition re-opens the stage and bumps
  `attempt`, so attempt 1 vs attempt 2 are distinguishable.

## Reconnection, dedupe and Redis expiry (AC3)

- Events are appended to `audit:job:{id}:events`; each append refreshes a
  **7-day TTL** (`AUDIT_JOB_EVENTS_TTL_SECONDS`). Replays are deterministic:
  the last transition per stage wins; duplicates are idempotent.
- Attempt 1 clears the events list at job start; attempts >= 2 keep it so
  reconnecting clients see earlier attempts.
- When the job hash survives but the events list has expired (or was never
  written): terminal jobs (`succeeded`/`failed`) report every stage as
  **`unknown`**; `queued`/`running` jobs report `pending`. Stage completion
  is never fabricated.
- Partial evidence on a terminal job marks unevented stages `unknown`.
- Stage history has no durable fallback: the job hash and `AuditJob` row hold
  status/timestamps only, so `unknown` is the truthful answer after expiry.

## Payload hygiene (AC5)

`normalize_stage_progress_event` is allowlist-only: `type`, `stage`,
`occurred_at`, `attempt`, `outcome` (degraded only), `reason`, `summary`.
Prompts, stack traces, raw provider responses and every cost/credit field are
dropped at ingestion. The polling response model has no credit/cost fields at
all, and the SSE `job_status` event serializes the same payload. A regression
test asserts the public payload contains no credit/cost/USD fragment.
