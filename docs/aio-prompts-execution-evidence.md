# AIO Prompts Table: Execution Trace and Field-to-Evidence Map (SIGV2-1010)

This document records how prompt measurements actually reach the AIO Prompts
table, what each rendered column is backed by, and which columns intentionally
return null-with-reason because no recorded evidence supports them.

## AC1: Scan request to table, honestly traced

There are **two unrelated measurement systems**, and conflating them is the
historical bug this ticket fixes:

| Path | Trigger | Writes to | Feeds the prompts table? |
|---|---|---|---|
| Audit scan (`AuditJob`) | User/API scan dispatch, 6 dispatch paths, gated by `scan_allowance_service` (SIGV2-1024) | `audit_runner.py` runs `GeoVisibilityService.run_visibility_audit` inline; result lands inside `audit.full_report` | **No.** The in-audit GEO visibility check does not create `VisibilityRunBatch`/`VisibilityRun` rows. |
| Visibility measurement | `visibility_index_worker.py` only: hourly project loop (`VISIBILITY_SCHEDULE_SECONDS`), Redis queue `visibility_index_jobs` (`blpop`), and the daily volatility seed pass | `VisibilityRunBatch` + `VisibilityRun` | **Yes**, exclusively. |

Trace of the only path that feeds the table:

1. `visibility_index_worker.run_worker` either pops a job payload
   (`topic`, `provider`, `schedule_key`, `project_id`, `target_domain`,
   `charge_user_id`, `charge_credits`, `audit_job_id`) off
   `visibility_index_jobs`, or the hourly loop enumerates
   `_load_project_visibility_jobs`: every active `ProjectVisibilityQuery` x
   each configured provider x each target domain (primary domain plus every
   `ProjectCompetitor` domain). Global `VISIBILITY_TOPICS` and volatility seed
   queries also produce batches with `project_id = NULL`.
2. `VisibilityIndexJobService.execute_batch` persists a `VisibilityRunBatch`
   (optionally charging scheduled visibility credits, idempotent per
   `schedule_key` via a deduped `UserCreditAdjustment.reason`), resolves the
   workspace-owner billing context + live-engine entitlement, then runs every
   prompt template (`load_prompt_templates_from_env`, overridable via
   `VISIBILITY_PROMPT_TEMPLATES_JSON`; defaults `market_overview` +
   `buyer_recommendation`).
3. `execute_prompt_run` renders the exact prompt (`{topic}`, `{provider}`,
   `{target_domain}` substituted), checks the v2-versioned semantic cache
   (identity includes engine source + model, so a proxy entry can never be
   served as live, SIGV2-1023), then calls the provider: OpenRouter when the
   global flag AND per-batch entitlement allow (`openrouter_live`), else the
   Bedrock measurement panel (`bedrock_proxy`). Live failures fall back to the
   proxy for that call. The `raw_response` dict records `model`,
   `engine_source`, `attempt`, `measured_at`, `run_id`,
   `served_from_cache`. Retries reuse the same `VisibilityRun` row, so a retry
   never duplicates a measurement; cache hits skip the provider call entirely
   and never consume allowance.
4. `parsed_citations` (all extracted) and `valid_citations` (validated
   URLs/DOIs) are persisted per run; the batch score is the mean of succeeded
   run scores.
5. `GET /api/v1/projects/{id}/monitoring/visibility-summary` aggregates the
   **latest** batch per (query_text, provider) across every origin, or, with
   `?audit_job_id=`, only the batches that scan triggered.

**Honest answers to the questions AC1 forbids guessing at:**

- No audit or scan mode currently enqueues visibility prompt measurements.
  `audit_job_id` exists (migration `20261004_010000`) and the worker consumes
  it from the queue payload, so a scan CAN own its batches, but nothing in the
  codebase pushes scan-linked payloads today. Scans populate the in-audit GEO
  visibility check only.
- There is **no fixed 30-prompt, 7-engine sweep**. Sweep size per schedule is
  `len(active queries) x len(query.providers) x len(target domains)` per
  project, each batch rendering `len(prompt_templates)` runs (2 by default).
  Which providers are measured live vs proxy depends on the global flag, the
  plan's `has_live_engine_tracking` capability, and per-region Bedrock
  availability (`bing` has no live path at all).
- Scheduled, queued, cached and volatility measurements all write the same
  tables; the `measurement_origin` field per cell keeps them explicitly
  identified (`scan`/`scheduled`/`queued`/`volatility`/`unknown`) with their
  real `measured_at`.

## Field-to-evidence map (every prompts-table column)

| Column | Serialized field | Backing evidence | Notes |
|---|---|---|---|
| Prompt | `queries[].query_text` | `ProjectVisibilityQuery.query_text`; exact rendered prompts per run at `queries[].results[].evidence.runs[].prompt` (+ `prompt_template`) | Configured query vs rendered prompt are both surfaced (AC3). |
| Type | `queries[].search_type` (canonical) alongside `queries[].query_type` (aeo/geo lane) | `query_taxonomy.classify_query_category` + `to_canonical`, same path as `compute_real_search_type_scores` | Canonical types reachable from query text: `comparison`, `feature`, `problem`, `category`. `brand` is NOT reachable from text classification alone (it requires a decision-making `query_type`, which visibility queries do not carry); queries whose text carries no category signal classify `category`, the documented `to_canonical` default. |
| Top engine | `queries[].top_engine` | Highest `score` among the row's completed cells (status `cited`/`not_cited`, numeric score). Winner returned with its cell `evidence`. | Rule documented in `_build_row_table_fields`. Returns `{provider: null, reason: "tied_providers"}` on a top-score tie, `{provider: null, reason: "no_completed_measurements"}` when nothing completed. Never invented. |
| You appear? | `queries[].results[].status` (existing `cited`/`not_cited`/`pending`/`failed`) + `queries[].results[].presence` | `valid_citations` matched against `batch.target_domain`; `text_mention` factor for mention-without-citation | `presence.state` is `domain_citation`, `brand_mention`, `measured_absent`, or `unmeasured`. Pending/failed/missing measurements are `unmeasured` with a reason, never "absent". A proxy-only absence carries `reason: "proxy_measurement_not_live"` — not a live-engine "no" (AC4). |
| Position | `queries[].position` | **None.** `parsed_citations` order is citation order, explicitly not recommendation rank (AC5); `score_breakdown.citation_position` is a scoring factor, not an ordinal. | Always `{value: null, reason: "ordinal_position_not_recorded"}`. If ordinal position evidence is ever persisted, this field takes it with its evidence reference. |
| Who wins | `queries[].who_wins` | Non-target domains across the row's `valid_citations` in succeeded runs, with counts and `run_ids`/`batch_ids` evidence; `is_configured_competitor` flags membership in `project.competitors` | Ordered by citation frequency then domain name. Not a recommendation rank. |

Provenance (AC3) per cell: `results[].measurement_origin`, `audit_job_id`,
`engine_source`, `model`, and `evidence{ batch_id, schedule_key, run_ids,
runs[{ run_id, prompt_template, prompt, status, score, model, engine_source,
served_from_cache, attempt, measured_at }] }`.

## Null-with-reason inventory

| Value | When | Reason code |
|---|---|---|
| `top_engine.provider` | No completed cells in the row | `no_completed_measurements` |
| `top_engine.provider` | Top score tied across providers | `tied_providers` |
| `position.value` | Always (no ordinal source recorded) | `ordinal_position_not_recorded` |
| `presence.state = unmeasured` | No batch for the cell | `no_measurement_recorded` |
| `presence.state = unmeasured` | Batch queued/running/retrying | `measurement_pending` |
| `presence.state = unmeasured` | Batch failed | `measurement_failed` |
| `presence.state = measured_absent` (proxy) | Completed proxy-only measurement, no evidence | `proxy_measurement_not_live` |
| `presence.state = measured_absent` (live) | Completed live measurement, no evidence | `no_evidence_in_measurement` |

## Compatibility and access

- All new fields are additive/Optional; `query_type`, `status`,
  `citations_found`, `score`, `score_breakdown` shapes are unchanged (AC6).
- `audit_job_id` on the summary endpoint only narrows the batch set; without
  it behaviour is identical to before (latest batch per query+provider).
- Project/tenant access is enforced by `_verify_project_access` before any
  batch data is read; evidence references only ever point at runs inside the
  caller's project (batches are filtered `project_id =`, foreign workspace
  members get 403/404).
- Retries and reloads: summary reads are side-effect free; retries reuse the
  same `VisibilityRun` row and cache hits skip provider calls, so no
  measurement or allowance consumption is duplicated (the scheduled credit
  charge dedupes on its `schedule_key`-bound reason; scan allowance is
  SIGV2-1024's `scan_allowance_service`).

## Pre-existing defects found while tracing (fixed in this diff)

- `_compute_batch_breakdown` passed the `raw_response` **dict** into
  `score_response` as the text argument, which raises `AttributeError` (500 on
  the summary endpoint) for every run persisted since SIGV2-1023 switched
  `raw_response` to a dict payload. Fixed by extracting the answer text
  (`_response_text`) before scoring.
