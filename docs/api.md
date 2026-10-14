# API Surface Snapshot

This document captures the newest API surface added in the current implementation pass.

The operator-facing in-app reference for this surface lives under `/dashboard/developer/docs`. The public marketing `/docs` route remains separate and is not the source of truth for headless API integration details.

## Orchestra V3 FAST, SMART, and DEEP Runtime

- no request contract changed in this pass
- the backend now includes the real internal FAST debate path in `backend/services/debate_orchestrator.py`:
  - `fast_proposer -> fast_critic -> fast_synthesizer`
  - all inter-agent transfers stay claim-ledger based rather than sending raw upstream JSON
  - FAST uses dedicated guardrails: `DEBATE_TOTAL_TIMEOUT_FAST_S`, `DEBATE_STEP_TIMEOUT_FAST_S`, and `DEBATE_COST_CAP_FAST_EUR`
- the backend now also includes the internal SMART V3 debate path:
  - `seo_generator + aeo_geo_generator -> centralized_critic -> smart_synthesizer -> magistrate`
  - the first layer runs in parallel
  - the synthesizer is intentionally routed on a fast-tier model
  - the magistrate returns the final canonical verdict on a smart-tier model
- the backend now also includes the internal DEEP_JUDGMENT Delta Flow:
  - `seo_generator + geo_generator + aeo_generator -> seo_critic + geo_critic + aeo_critic -> consolidator -> global_magistrate`
  - the first two layers run in parallel
  - all inter-agent transfers stay compact and domain-scoped
  - degraded fallbacks keep the run alive if one generator, one critic, the consolidator, or the magistrate fails
- Anthropic debate steps now apply provider-aware prompt budgets before invocation:
  - transfer, critique, consolidated, and audit-data sections are truncated to configurable char ceilings
  - Anthropic payload-size failures fall back per agent to a non-Anthropic route
- V3 activation is still gated by `ORCHESTRA_V3_MOAT_READY`; default `false` keeps FAST audits on the single-call path, SMART audits on the current legacy/provider-specific runtime, and DEEP_JUDGMENT on the current legacy/provider-specific high-confidence runtime until TASK-90 moat ingestion is ready
- additive debate metadata emitted when the V3 debate path runs now includes:
  - `mode = "debate"`
  - `provider = "multi-provider"`
  - `model = "multi-agent"`
  - `requested_tier`
  - FAST: `profile = "fast_3step"`
  - SMART: `profile = "smart_5step"`
  - DEEP_JUDGMENT: `profile = "delta_flow"`
  - `pipeline_type`
  - `agent_count`
  - `parallel_layers`
  - `per_agent_costs[]`
  - transcript route metadata such as `semantic_role`, `requested_tier`, `execution_tier`, `routing_mode`, and `layer`
  - `quality_gate` with `schema_version`, `passed`, `thresholds`, `agent_checks[]`, and `violations[]`
  - `usage`

## Admin System Status - Orchestra V3 Readiness

- affected route:
  - `GET /api/v1/system-status/admin`
- all affected responses continue returning `X-Request-ID`
- additive admin-only response block:
  - `orchestra_v3_readiness.status`: `ready | blocked`
  - `orchestra_v3_readiness.ready_for_controlled_test_audits`: boolean derived from current env and service blockers
  - `orchestra_v3_readiness.debate_enabled`
  - `orchestra_v3_readiness.moat_ready`
  - `orchestra_v3_readiness.operational_providers[]`
  - `orchestra_v3_readiness.blockers[]`: `{ code, title, detail }`
  - `orchestra_v3_readiness.warnings[]`: `{ code, title, detail }`
  - `orchestra_v3_readiness.manual_follow_ups[]`: still-manual rollout steps that operators must complete outside the automated checks
- behavior:
  - the readiness block is intended for pre-production operators deciding whether controlled real Orchestra V3 test audits can start in the current environment
  - it does not attempt to automate the human TASK-92 calibration loop or the final canary/shadow rollout signoff

## Admin Debate Trace

- affected admin routes:
  - `GET /api/v1/admin/audits/{audit_id}/debate-trace`
  - `GET /api/v1/admin/audits/{audit_id}/debate-trace/{role}/output`
  - `GET /api/v1/admin/audits/{audit_id}/debate-trace/claim/{claim_id}/journey`
- all affected responses continue returning `X-Request-ID`
- behavior:
  - returns the persisted `debate_traces` timeline for one audit, grouped into execution layers with latency, USD cost, token counts, output previews, and compact claim/challenge counts
  - returns one agent’s encrypted-at-rest stored prompt payload plus full raw output for admin-only debugging
  - returns a best-effort claim journey by matching a `claim_id` through stored generator ledgers, critic challenge packets, consolidator dispositions, and downstream judge-review inputs
- storage contract:
  - debate traces are persisted outside `audits.full_report`
  - raw input/output payloads are encrypted at rest through the shared `EncryptedText` column type
  - compact `output_claim_ledger` snapshots are stored as JSON for fast timeline/journey lookups

## Report Export Manifest (AUD-16A)

- affected routes:
  - `POST /api/v1/reports/generate-complex`
  - `POST /api/v1/reports/white-label/pdf`
- all affected responses continue returning `X-Request-ID`
- legacy `report_type` remains accepted, but the backend now normalizes exports onto an internal manifest before queueing PDF work

### Request contract additions

Shared export controls now include:

- `report_kind`: `standard | executive | project | competitors | financial`
- `branding_mode`: `platform | white_label`
- `competitor_mode`: `latest | trend`
- `hide_credit_cost`: boolean, default `true`

Notes:

- `competitor_mode` is valid only for competitor report exports
- `date_from` must be earlier than or equal to `date_to` on complex report requests
- legacy `report_type` values (`standard | battle | branded | whitelabel`) still map onto the new manifest for backward compatibility

### Worker payload behavior

Queued PDF jobs now persist an additive `export_manifest` block alongside `options` and `branding_config`. The manifest currently includes:

- `report_kind`
- `branding_mode`
- `competitor_mode`
- `hide_credit_cost`
- `legacy_report_type`
- `render_report_type`
- `template_type`

### Rendering behavior

- `export_manifest.report_kind` is now the authoritative routing key for PDF rendering and worker orchestration
- the PDF assembler now exposes `export_manifest`, `context_page`, and `integrity_page` in template context
- when `hide_credit_cost=true`, cost/credit disclosure fields are stripped from the render context before template rendering, and financial exports switch to an explicit withheld notice when the assembled financial payload is marked redacted
- white-label and legacy shell behavior remain backward-compatible at the request level, but project and financial exports now assemble through the normalized report-suite pipeline instead of falling back to the standard shell

## Grounded Strategic Insights (AUD-05)

- `POST /api/v1/ai/strategic-insights`
- auth: authenticated user, with project RBAC enforced when the audit belongs to a project
- all affected responses continue returning `X-Request-ID`

### Request contract

- `audit_id`: required integer ID of a persisted audit
- `project_id`: optional integer; when supplied, the audit must belong to that project

### Runtime behavior

- no arbitrary prompt input is accepted
- the backend resolves the saved audit, canonicalizes the report, and enriches the result with project profile, target keywords, project visibility runs, and AEO/GEO tracker history when available
- saved tracker rows remain manual hypotheses until a real project visibility run exists; tracker history does not create synthetic measured citations
- project-backed requests reject inaccessible or mismatched audit/project pairs; non-project audits fall back to owner-only access

### Response payload

- response shape remains `{ "content": "<json-string>" }`
- the serialized JSON now includes:
  - `generated_at`, `audit_id`, `project_id`
  - `grounding_sources`
  - `executive_summary`
  - `critical_alerts`
  - `priority_roadmap`
  - `content_gap_theory`
  - `technical_debt_explanation`
  - `aeo_query_ideas`
  - `geo_prompt_ideas`
- each AEO/GEO idea includes:
  - `text`
  - `confidence`
  - `label` (`measured`, `inferred`, or `hypothesis`)
  - `source_basis`
  - `status_note`
  - `last_verified_at`

## Brand Audit Target Contract (STX-31)

- all affected routes continue returning `X-Request-ID`
- legacy URL-only clients remain supported

### Request contract additions

- `POST /api/v1/audit`
- `POST /api/v1/audit/jobs`

Accepted target fields:

- `audit_target_type`: `website | brand` (default `website`)
- `url`: legacy website URL (still accepted)
- `target_url`: normalized URL target (used as the canonical legacy `url` bridge)
- `target_name`: required when `audit_target_type=brand`
- `target_metadata`: free-form JSON metadata for aliases/entities/domains

Validation behavior:

- `website` requires `url` or `target_url`
- `brand` requires `target_name`
- URL-less brand execution is supported for authenticated sync and queued audits; technical probes are skipped and persisted records keep `target_url = null` with legacy `url = ""`

### Sync audit cache control

- affected route:
  - `POST /api/v1/audit`

Optional request field:

- `cache_behavior`: `default | bypass` (default `default`)

Runtime behavior:

- `default` preserves the existing audit report cache lookup/store flow
- `bypass` skips cache replay for that sync audit request, executes the current runtime path, and still refreshes the stored cache entry after the new report is generated
- sync audit report metadata now includes:
  - `cache_behavior`
  - `cache_state` (`hit`, `miss`, or `bypass`)

Recommended use:

- validation reruns for `EPIC-03` should use `cache_behavior=bypass` when re-auditing the same target/provider/tier subject, so signoff compares the current runtime behavior instead of a replayed cached report

### Guest audit target-mode contract (STX-34)

- `POST /api/v1/guest-audit` now accepts:
  - `audit_target_type`: `website | brand` (default `website`)
  - `url` / `target_url`
  - `target_name` (required for `brand`, `entity` remains accepted as compatibility alias)
  - `target_metadata` (optional JSON object)
- guest runtime behavior:
  - `website`: URL is required and technical probes run (scraper + performance + network)
  - `brand` with URL: target-aware run with technical probes
  - `brand` without URL: allowed; technical probes are skipped and response insights explain the skipped diagnostics
- guest response now includes canonical target context:
  - top-level `target` object (`type`, `name`, `url`, `metadata`)
  - canonical sections (`site`, `seo`, `geo`, `aeo`, `scores`)
  - mirrored metadata target keys (`audit_target_type`, `target_name`, `target_url`, `target_metadata`)

### Response contract additions

- `GET /api/v1/audits/history`
- `GET /api/v1/audits/{audit_id}`
- `GET /api/v1/audit/jobs/{job_id}`
- `GET /api/v1/projects/{project_id}`
- `GET /api/v1/projects/{project_id}/audits`
- `GET /api/v1/projects/{project_id}/audits/latest`
- `GET /api/v1/projects/{project_id}/audits/latest-selection?module=seo|aeo|geo`

Added fields:

- `site_id` on `GET /api/v1/projects/{project_id}/audits` and `GET /api/v1/projects/{project_id}/audits/latest`
- `audit_target_type`
- `target_name`
- `target_url`
- `target_metadata`
- `feature_access` on `GET /api/v1/projects/{project_id}` and workspace project-list payloads

### Audit job live progress stream

- `GET /api/v1/audit/jobs/{job_id}/events`
- transport: `text/event-stream`
- event names emitted by the public stream:
  - `job_status`
  - `pipeline_started`
  - `layer_started`
  - `layer_completed`
  - `step_started`
  - `step_completed`
  - `debate_finished`
- behavior:
  - reuses the existing audit-job SSE route rather than a separate debate-only endpoint
  - streams sanitized Orchestra V3 progress metadata from Redis-backed job events
  - keeps summaries capped at 200 chars and never exposes raw prompts, full intermediate outputs, or claim-ledger payloads
- V3 event payload additions may include:
  - `pipeline_type`
  - `total_agents`
  - `parallel_layers`
  - `estimated_duration_s`
  - `layer`
  - `layer_name`
  - `agents_in_layer`
  - `parallel`
  - `domain`
  - `latency_ms`
  - `total_latency_ms`
  - `agents_completed`
  - `agents_failed`
  - `total_cost_eur`

Module-aware latest audit selection responses now include:

- `status` (`ready` | `stale` | `no_matching_audit` | `no_audits`)
- `message`
- `recommended_audit_type`
- `recommended_launch_tier`
- `compatible_audit_types`
- `stale_after_days`
- `selected_audit_age_days`
- `selected_audit`
- `latest_audit`

Canonical report payloads now include:

- top-level `target` object: `{ type, name, url, metadata }`
- `metadata.locked_sections` when the caller's current plan does not allow premium audit sections present in stored historical data
- read-time sanitization on audit detail/history/project audit payloads, so locked premium sections are omitted from JSON instead of merely hidden in the UI
- mirrored metadata keys: `audit_target_type`, `target_name`, `target_url`, `target_metadata`
- frontend consumers now treat `schema_version` as mandatory whenever a payload already looks canonical (`site` / `seo` / `geo` / `aeo` / `scores`); canonical-looking payloads without it are rejected and rendered as degraded schema-mismatch states instead of being normalized heuristically

### Dual-Track trust contract additions (EPIC-03)

The canonical audit/report payload can now carry additive dual-track trust metadata without breaking legacy consumers.

Claim-level grounding rows under `hallucination.claim_verifications[]` may now include:

- `track`: `track_a | track_b | mixed`
- `claim_kind`
- `classification_basis[]`
- `premise_refs[]`
- `evaluation_mode`
- `reason_codes[]`
- `problem_refs[]`
- `problem_anchor_score`
- `action_fit_score`
- `site_specificity_score`
- `novel_fact_risk_score`
- `suggested_rewrite`

Canonical report payloads may now also include:

- `integrity_certificate`
  - `schema_version`
  - `dual_track_grounding_enabled`
  - `grounding_profile`
  - `summary`
    - `total_claims`
    - `track_a_total`, `track_a_supported`, `track_a_flagged`, `track_a_omitted`
    - `track_b_total`, `track_b_supported`, `track_b_flagged`, `track_b_omitted`
  - `blocked_claim_buckets[]`
    - `track`
    - `category`
    - `count`
  - `degraded`
  - `degraded_reason`

Runtime metadata persisted with audit payloads may include:

- `metadata.dual_track_shadow`
  - shadow-only comparison payload for `Track A` / `Track B`
  - includes `summary`, `atomization`, `track_b_judge`, and per-claim comparison rows
- `metadata.grounding_profile`
- `metadata.dual_track_grounding_enabled`
- `metadata.fallback_reason`
- `metadata.integrity_certificate_summary`

Compatibility notes:

- dual-track fields are additive and optional
- `certainty_score`, `disposition`, and `evidence_refs` remain the backward-compatible minimum contract
- `integrity_certificate` may be absent on legacy or fallback runs
- client-safe report surfaces may summarize blocked `Track B` recommendations separately from factual hallucination handling; consumers must not assume every blocked strategic claim is a hallucination

### Operator rollout and observability endpoints

- `GET /api/v1/admin/observability/dual-track-grounding`
  - auth: admin user
  - behavior: returns the canonical deep-judgment runtime semantics plus local-process dual-track counters
  - response includes:
    - canonical runtime snapshot (`mode`, `effective_scope`, `source`)
    - `metrics.claims`
    - `metrics.reason_codes`
    - `metrics.fallback_reasons`

- `GET /api/v1/admin/observability/prompt-quality-gate`
  - auth: admin user
  - query params:
    - `days` (optional, `1..30`, default `7`)
    - `tier` (optional, one of `fast`, `smart`, `deep_judgment`)
  - behavior:
    - scans recent audits for persisted `debate.quality_gate` metadata emitted by moat-ready Orchestra V3 debate runs
    - returns aggregate failure counts, top violation codes, tier summaries, recent failing audits, and a previous-window comparison for prompt calibration work
  - response includes:
    - `schema_version`
    - `window_days`
    - `audits_checked`, `audits_failed`, `failure_rate`
    - `thresholds`
    - `top_violations[]`
    - `tier_summary`
    - `recent_failures[]`
    - `comparison.previous_window`
    - `comparison.deltas`

- `GET /api/v1/admin/observability/prompt-quality-calibration`
  - auth: admin user
  - query params:
    - `days` (optional, `1..30`, default `7`)
    - `limit` (optional, `1..100`, default `20`)
    - `tier` (optional, one of `fast`, `smart`, `deep_judgment`)
    - `audit_id` (optional, repeatable integer filter; when present the endpoint targets those exact audits instead of a rolling window)
  - behavior:
    - summarizes recent Orchestra V3 audits using the persisted `debate.quality_gate` block plus `DebateTrace` coverage
    - highlights which audits are actually calibration-ready and suggests the prompt files most likely to inspect first
  - response includes:
    - `schema_version`
    - `summary.audits_considered`, `summary.audits_with_traces`, `summary.calibration_ready_audits`, `summary.calibration_ready_failures`
    - `top_violations[]`
    - `audits[]` with `missing_artifacts`, `calibration_ready`, `violation_codes`, and `suggested_prompt_files`

- `GET /api/v1/admin/audits`
  - auth: admin user
  - additive filter params:
    - `grounding_profile`
    - `dual_track_grounding_enabled`
    - `fallback_reason`
  - additive row fields may include:
    - `grounding_profile`
    - `dual_track_grounding_enabled`
    - `fallback_reason`
    - `requested_tier`
    - `track_a_claim_count`
    - `track_b_claim_count`
    - `rollout_mode`
    - `effective_execution_mode`

## Audit Cost Forecasting & Estimate API (STX-37)

- all affected routes return `X-Request-ID`

### Estimate endpoint

- `POST /api/v1/audit/estimate`
  - auth: authenticated user
  - body:
    - `provider`, `tier`
    - optional `category`, `market`, `entities`
    - optional `selected_models`, accepted and ignored (see the model selection note below)
    - optional `audit_target_type`, `target_name`, `target_url`, `target_metadata`
    - optional `audit_data` (pre-scan/content seed)
    - optional `serp_preview` (pre-scan SERP seed)
  - behavior:
    - resolves the effective audit route server-side; a submitted `provider` / `selected_models` is discarded first (see the model selection note below)
    - enforces both plan gating and the server-owned High Confidence rollout policy when `tier=deep_judgment`
    - forecasts model-aware token/infra/SERP cost using the shared cost forecast service
    - preserves brand target identity in forecast inputs instead of coercing `target_name` from `target_url`
    - applies trailing-ledger calibration when recent economics data exists
    - returns wallet sufficiency for the authenticated user
  - response includes:
    - `provider`
    - `tier`
    - `estimated_credit_cost`
    - `estimated_credits`
    - `estimated_cost_eur`
    - `confidence`
    - `available_credits`
    - `sufficient_balance`
    - `breakdown` (`forecast_mode`, resolved route, density signals, per-step projections, selected models)

### Audit create/job forecast propagation

- `POST /api/v1/audit`
- `POST /api/v1/audit/jobs`
  - auth: authenticated user
  - behavior:
    - both routes build/persist a `cost_forecast` payload before execution/dispatch
    - synchronous audits attach forecast metadata to the persisted report alongside TASK-36 credit-hold settlement data
    - queued job payloads persist `cost_forecast` so worker execution, hold settlement, and economics-ledger writes use the same estimate family
    - the resolved model list is persisted with the routed audit metadata and used by both sync and queued consensus execution paths
  - model selection note (SIGV2-1139):
    - `provider` and `selected_models` are accepted by the schema and then discarded on every plan (`_strip_client_model_selection`), so the resolved route is always the server's. Choosing the models that run an audit is not a capability of any plan, and there is no capability key for it: SIGV2-1120 removed `has_custom_ai_model_routing` from `CAPABILITY_MATRIX`, `CAPABILITY_DESCRIPTIONS` and the pricing matrix, where it had been false on every plan with no runtime reader. The Enterprise tier the old gate was named after was removed from the product, and no screen offers the control.
    - the strip is what keeps a caller from steering which paid provider executes an audit, and from forcing `multi_model_consensus` mode, which runs one projected provider step per selected model plus a synthesis step as soon as 2+ models survive. Internal callers (workflow actions) reach the routing policy directly and are not affected.

## Pricing Policy v2 Controls

- all admin routes return `X-Request-ID`

### Operations status

- `GET /api/v1/admin/operations`
  - auth: admin user (`get_current_admin_user`)
  - behavior: returns operational switches used by runtime services
  - response includes:
    - `fallback_model_enabled`
    - `pricing_v2_enabled`
    - `credit_engine_v2_enabled`
    - `pricing_v2_shadow_mode`
    - `cache_refresh_requested_at`
    - `report_retention_days`

### Pricing flag mutation

- `POST /api/v1/admin/operations/pricing-v2`
  - auth: admin user (`get_current_admin_user`)
  - body: any subset of:
    - `pricing_v2_enabled`
    - `credit_engine_v2_enabled`
    - `pricing_v2_shadow_mode`
  - behavior:
    - validates at least one field is supplied
    - persists operational flag changes
    - logs audit trail entry `pricing_v2_flags_updated`
    - returns the updated operations status payload

## Admin Billing Runtime & Stripe Catalog (TASK-38)

- all admin billing routes return `X-Request-ID`
- billing/admin code paths now accept only canonical plan IDs:
  - `plan_standard`
  - `plan_specialist`
  - `plan_executive`

### Runtime config surface

- `GET /api/v1/admin/billing/config`
  - auth: authenticated admin user
  - behavior: returns the effective billing runtime snapshot for the admin payments screen
  - response includes:
    - `billing_enabled`
    - `stripe_mode`
    - `stripe_mode_source`
    - `has_runtime_override`
    - `modes[]` with per-mode secret/webhook presence and hints
    - `price_ids[]` for the four canonical plans
    - `commitment_price_ids[]` for `growth`, `scale`, and `enterprise`
    - `commitment_overage_price_ids` for the shared overage meter

- `PATCH /api/v1/admin/billing/config`
  - auth: authenticated admin user
  - body supports any subset of:
    - `billing_enabled`
    - `stripe_mode`
    - `test_secret_key`, `live_secret_key`
    - `test_webhook_secret`, `live_webhook_secret`
    - `test_price_ids`, `live_price_ids`
    - `test_commitment_price_ids`, `live_commitment_price_ids`
    - `test_commitment_overage_price_id`, `live_commitment_overage_price_id`
  - behavior:
    - persists mode-specific runtime overrides under `OperationalSetting.admin_settings_payload["billing_runtime"]["modes"][mode]`
    - keeps `stripe_mode` as an explicit admin switch; catalog sync does not change it implicitly

### Stripe catalog sync

- `POST /api/v1/admin/billing/catalog/sync`
  - auth: authenticated admin user
  - body:
    - `mode`: `test | live`
    - `scope`: `plans | commitments | all` (default `all`)
    - `dry_run`: `boolean` (default `false`)
  - behavior:
    - uses the requested mode's Stripe secret key from `load_billing_config(...).mode_configs[mode]`
    - derives canonical product/price definitions from code, not hardcoded Stripe IDs
    - reuses matching managed Stripe prices when possible and creates missing managed products/prices otherwise
    - writes generated IDs back to `billing_runtime.modes[mode]` when `dry_run=false`
    - does not flip the active `stripe_mode` when syncing a non-active mode
  - response includes:
    - `mode`, `scope`, `dry_run`
    - `result.items[]` with `kind`, `key`, `product_id`, `price_id`, `action`, `message`
    - `result.plan_price_ids`
    - `result.commitment_price_ids`
    - `result.commitment_overage_price_id`
    - `result.warnings[]`
    - refreshed `config`

### Stripe catalog validation

- `POST /api/v1/admin/billing/catalog/validate`
  - auth: authenticated admin user
  - body:
    - `mode`: `test | live`
    - `scope`: `plans | commitments | all` (default `all`)
  - behavior:
    - validates the configured Stripe `price_...` IDs for the requested mode against the canonical code-derived catalog
    - does not mutate runtime settings or Stripe resources
  - response includes:
    - `mode`, `scope`
    - `results[]` with `kind`, `key`, `configured_price_id`, `status`, `message`, `expected`, and `actual`
    - status values: `valid | unconfigured | missing | mismatch`
    - refreshed `config`

## Headless API Product

### API key management

- `GET /api/v1/settings/api-keys`
  - auth: authenticated agency user, denied for `portal_only`
  - behavior: lists persisted API keys, current plan, plan-lock state, and developer hub link

- `POST /api/v1/settings/api-keys`
  - auth: authenticated agency user on active `plan_specialist` or `plan_executive`
  - body: `{ "name": "Warehouse Export", "scopes"?: ["audit:read", "audit:write"] }`
  - behavior: creates a new `stx_live_*` key, stores only the hash, and returns the raw key exactly once
  - scopes: must come from the allow-list published by `GET /api/v1/external/sdk-metadata`; anything else is rejected with `422`
  - omitting `scopes` grants read access only, so starting a paid audit (`audit:write`) has to be asked for

- `DELETE /api/v1/settings/api-keys/{api_key_id}`
  - auth: authenticated agency user, denied for `portal_only`
  - behavior: revokes the key and marks it inactive without exposing the raw credential again

### External audit API

- auth: `Authorization: Bearer stx_live_*` or `X-API-Key: stx_live_*`
- all routes return:
  - `X-Request-ID`
  - `X-RateLimit-Limit`
  - `X-RateLimit-Remaining`
  - `X-RateLimit-Reset`
- `429` also returns `Retry-After`

- `POST /api/v1/external/audit`
  - auth: API key with `audit:write`
  - body: `url`, `tier`, optional `provider`, `project_id`, `webhook_url`, `webhook_secret`, `idempotency_key`, entity/category/market/language fields
  - behavior: validates plan eligibility, project access, rate limits, idempotency, and estimated credit cost, then enqueues a shared audit job
  - returns: `202 Accepted` with `job_id`, `estimated_credit_cost`, `poll_url`, and optional `webhook_secret`

- `POST /api/v1/external/audit/bulk`
  - auth: API key with `audit:write`
  - body: `{ "items": [ ... up to 50 audit payloads ... ] }`
  - behavior: queues multiple external audits and returns per-item success or error details

- `GET /api/v1/external/audit/{job_id}`
  - auth: API key with `audit:read`
  - behavior: returns persisted external job state, scores, provider/tier, credit cost, webhook status, and `report_url` when available

- `GET /api/v1/external/audit/{job_id}/report`
  - auth: API key with `audit:read`
  - behavior: returns the normalized audit JSON for completed external audits, sanitized against the caller's current plan with `metadata.locked_sections` for locked premium sections

- `GET /api/v1/external/projects/{project_id}/scores/csv`
  - auth: API key with `audit:read`
  - query: `start_date`, `end_date`, `limit`
  - behavior: downloads project-linked audit history as CSV with `project_id`, `audit_date`, `geo_score`, `seo_score`, `aeo_score`, `url`, `entity_count`, and `recommendation_count`

- `GET /api/v1/external/export`
  - auth: API key with `audit:read`
  - query: repeated `project_id`, `start_date`, `end_date`, `limit`
  - behavior: bulk CSV export across one or more accessible projects using the same connector-ready schema

- `GET /api/v1/external/audits`
  - auth: API key with `audit:read`
  - query: `page`, `page_size`
  - behavior: paginated list of external audit jobs for the key owner

- `GET /api/v1/external/projects/{project_id}/tasks`
  - auth: API key with `projects:read`
  - query: `status` (`TODO`, `IN_PROGRESS`, `DONE`), `page`, `page_size`
  - behavior: lists the project's tasks with the status summary; project tasks are part of project data, so there is no separate task scope

- `GET /api/v1/external/projects/{project_id}/tasks/{task_id}`
  - auth: API key with `projects:read`
  - behavior: returns one task belonging to the project

### MCP server

The Qiko Signal MCP server, for connecting an AI agent to a workspace's visibility data.

- endpoint: `POST /api/v1/mcp`
- transport: Streamable HTTP, JSON responses, stateless
- protocol versions: `2025-11-25`, `2025-06-18`, `2025-03-26`, negotiated on `initialize`
- methods: `initialize`, `ping`, `tools/list`, `tools/call`, and notifications
- plan gate: `mcp_access`, which is Specialist and Executive only. This is a separate
  entitlement from `api_access`, which the Agency Trial also holds; the trial does not get the
  MCP server. The gate applies to every method, so an ineligible plan cannot reach `tools/call`
  by naming a tool it was never shown.
- auth: the same API key as the REST surface, `Authorization: Bearer stx_live_*` or
  `X-API-Key: stx_live_*`. This is not OAuth: no authorization server exists to discover, so a
  `401` carries a plain `WWW-Authenticate: Bearer` challenge and advertises no
  protected-resource metadata.
- rate limits: the per-key plan limits, applied per MCP call, with the same `X-RateLimit-*`
  headers and `Retry-After` on `429`
- `GET` and `DELETE` on the endpoint return `405`: the server initiates no messages, so there is
  no event stream to open, and it holds no session, so there is nothing to delete.
- error codes beyond the JSON-RPC reserved range: `-32003` the key lacks the tool's scope, the
  plan lacks the underlying feature, or the work was refused; `-32004` the project, audit or
  scan does not exist for this caller. A record belonging to another workspace is reported as
  absent, not as forbidden.

Client support, as of this release:

- **Claude** (`claude.ai` custom connectors, Claude Desktop, Claude Code) connects with the API
  key in a request header. On the hosted surfaces an organisation Owner adds the connector with
  authentication set to "No sign-in" and the key under Request headers (`X-API-Key` or
  `Authorization`); that static-credential mode is in beta and is enabled per organisation.
  Claude Code takes the header directly on the command line.
- **ChatGPT** connectors and the OpenAI Responses API `mcp` tool accept a bearer token, and
  Codex supports bearer tokens on Streamable HTTP servers. The ChatGPT developer-mode connector
  UI expects OAuth 2.1 with protected-resource discovery for anything acting on a user's behalf,
  which this server does not implement, so a key-authenticated connection there is not
  guaranteed. No partial OAuth flow is shipped: an authorization server is a separate decision,
  recorded on the ticket.
- Any client that only speaks stdio can use `scripts/mcp_stdio_bridge.py`, which proxies to this
  endpoint and holds no logic of its own.

The bridge needs one environment variable, the API key:

```yaml
command: python3
args: ["/path/to/mcp_stdio_bridge.py"]
env:
  QIKO_SIGNAL_API_KEY: "stx_live_..."
```

It posts to `https://qiko.ai/signal/api/v1/mcp` by default, the same base the Developer Hub
prints in its code samples with `/mcp` on the end. Set `QIKO_SIGNAL_MCP_URL` to point it
anywhere else, which is what a workspace on preprod or a local stack needs:

```yaml
env:
  QIKO_SIGNAL_MCP_URL: "https://signal.preprod.qiko.ai/api/v1/mcp"
  QIKO_SIGNAL_API_KEY: "stx_test_..."
```

The override must be `https`, because the key is a bearer credential and the bridge will not
send it in cleartext. Plain `http` is accepted only for `localhost`, where there is no network
to listen on.

#### Cost

One tool spends money. `signal_run_audit` consumes one scan from the plan's rolling 30-day scan
allowance, counted by the same service as every other audit launch, and says so in its own
description. It is advertised with `readOnlyHint: false`, so a client that asks for approval
before non-read calls will ask before this one. Every other tool is a read and cannot be charged
for.

Three refusals are deliberately legible, each with `data.retryable: false`, so an autonomous
client stops instead of retrying:

- the allowance is exhausted: says how many scans the plan allows, that nothing was charged, and
  when the window resets
- an audit of the same project is already running: says to poll `signal_get_scan_status`
- the plan does not include the feature behind the tool

Retrying `signal_run_audit` for the same project and tier within about ten minutes returns the
original job rather than starting a second paid audit, through a server-derived idempotency key.
While an audit is running, the in-flight dedup refuses a duplicate for its whole duration.

Tools, each with the scope its caller must hold:

- `signal_list_projects`
  - scope: `projects:read`
  - arguments: `limit` (1-100, default 20)
  - returns: each project's id, name, domain, target country, language and creation date, for the
    workspaces the key's identity owns or is a non-client member of

- `signal_get_project`
  - scope: `projects:read`
  - arguments: `project_id`
  - returns: the project's details plus its most recent audit's id and scores

- `signal_get_audit`
  - scope: `audit:read`
  - arguments: `project_id`, optional `audit_id` (omit for the most recent audit)
  - returns: the audit's SEO, GEO and AEO scores plus one overall visibility score, its target and
    tier. Competitor benchmark audits are excluded, so these are the project's own measurements.

- `signal_list_audits`
  - scope: `audit:read`
  - arguments: `project_id`, `limit` (1-50, default 10)
  - returns: the project's own audits newest first, each with its id, tier, scores and completion
    time, for reading a trend without fetching each audit

- `signal_get_audit_breakdown`
  - scope: `audit:read`
  - arguments: `project_id`, optional `audit_id` (omit for the most recent audit)
  - returns: the per-engine detail of one audit: each of the SEO, AEO and GEO pillar scores with
    up to five headline findings behind it. The rest of the stored report, including raw evidence
    and model reasoning, is not returned.

- `signal_list_recommendations`
  - scope: `projects:read`
  - arguments: `project_id`, optional `status` (`TODO`, `IN_PROGRESS`, `DONE`), `limit` (1-100,
    default 20)
  - returns: each recommendation's headline, category, priority and state. The full recommendation
    body and the assignee are deliberately not returned: a tool result crosses into an agent's
    context, and neither field answers what the project should fix next.

- `signal_list_competitors`
  - scope: `competitors:read`
  - arguments: `project_id`
  - returns: each tracked competitor's id, display name, domain and most recent SEO, AEO and GEO
    scores. Requires a plan including competitor analysis, enforced per call.

- `signal_list_schedules`
  - scope: `schedules:read`
  - arguments: optional `project_id`, `limit` (1-100, default 20)
  - returns: each recurring audit schedule's id, project, frequency, tier, active state and next
    and last run. With no `project_id` the listing is bounded by the key's reachable projects.

- `signal_list_alerts`
  - scope: `alerts:read`
  - arguments: `project_id`
  - returns: each alert rule's id, watched metric, comparator, threshold, active state and when it
    last fired

- `signal_get_scan_allowance`
  - scope: `audit:read`
  - arguments: none
  - returns: the plan's scan limit, scans used in the current rolling 30-day window, scans
    remaining and when the window resets. Call it before `signal_run_audit` to see whether a scan
    is available rather than discovering it through a refusal.

- `signal_get_scan_status`
  - scope: `audit:read`
  - arguments: `job_id`
  - returns: the scan's status, tier, project and, once it has finished, its scores or its error.
    Only scans submitted through the API by this key's identity are visible.

- `signal_run_audit`
  - scope: `audit:write`
  - arguments: `project_id`, `tier` (`fast`, `smart` or `deep_judgment`, default `fast`)
  - **consumes one scan from the plan scan allowance.** Starts an audit of the project's own
    registered domain; there is no `url` argument, so the tool cannot be aimed at any other
    address. Returns the job id to follow with `signal_get_scan_status`, the target, and the
    allowance after the launch. `audit:write` is outside the default scope grant, so a key
    created without an explicit scope list cannot call it.

## Project AI Bot Log Analyzer

- plan gate: `api_access` (Specialist / Executive)
- all endpoints return `X-Request-ID`

### Summary + sources

- `GET /api/v1/projects/{project_id}/monitoring/bot-logs/summary`
  - auth: authenticated project member (`ADMIN`/`EDITOR`/`VIEWER`/assigned `CLIENT_READONLY`)
  - query: `days` (`7..365`, default `30`)
  - behavior: returns aggregated AI crawler diagnostics (total hits, verified vs spoofed, 4xx/5xx waste, section heatmap, spoofing radar, latest upload metadata, source list)

- `GET /api/v1/projects/{project_id}/monitoring/bot-logs/sources`
  - auth: authenticated project member (read access)
  - behavior: returns persisted ingestion-source configs for `manual_upload`, `cloudflare_logpush`, `aws_s3`, `gcp_cloud_storage`

- `POST /api/v1/projects/{project_id}/monitoring/bot-logs/sources`
  - auth: authenticated project member with workspace write access (`ADMIN`/`EDITOR`)
  - body: `{ "source_type": "...", "display_name"?: "...", "config"?: {...}, "is_active"?: true }`
  - behavior: upserts project-scoped source config and activation state

### Upload ingestion

- `POST /api/v1/projects/{project_id}/monitoring/bot-logs/upload`
  - auth: authenticated project member with workspace write access (`ADMIN`/`EDITOR`)
  - body: multipart file field `file` (`.log`, `.txt`, `.gz`)
  - query:
    - `source_type` (optional, defaults to `manual_upload`)
    - `source_id` (optional, validates project ownership)
  - behavior: streams server log parsing, matches known AI bot user agents, applies reverse-DNS verification for spoofing detection, persists per-upload aggregates, and refreshes daily summaries

## Project AI Search Volatility Index

- plan gate: `api_access` (Specialist / Executive)
- all endpoints return `X-Request-ID`

### Project summary + trends

- `GET /api/v1/projects/{project_id}/monitoring/ai-search-volatility/summary`
  - auth: authenticated project member (`ADMIN`/`EDITOR`/`VIEWER`/assigned `CLIENT_READONLY`)
  - query:
    - `provider` (default `all`)
    - `days` (`7..365`, default `30`)
  - behavior: returns latest global volatility score, weather label, component metrics, industry breakdown, and top citation winners/losers

- `GET /api/v1/projects/{project_id}/monitoring/ai-search-volatility/trends`
  - auth: authenticated project member (read access)
  - query:
    - `provider` (default `all`)
    - `days` (`7..365`, default `30`)
  - behavior: returns date-series volatility points (`volatility_score`, `compared_queries`, `changed_ratio`) used for monitoring cards and timeline correlation

### Public dashboard

- `GET /api/v1/volatility/public`
  - auth: none
  - query:
    - `provider` (default `all`)
    - `days` (`7..365`, default `30`)
  - behavior: returns pre-aggregated public payload (`available_providers`, `summary`, `trends`, `industry_matrix`, `citation_ledger`) consumed by `/volatility`

## Project Off-Page AEO Mentions Tracker

- plan gate: `api_access` (Specialist / Executive)
- all endpoints return `X-Request-ID`

### Summary, trends, and feed

- `GET /api/v1/projects/{project_id}/monitoring/off-page-mentions/summary`
  - auth: authenticated project member (`ADMIN`/`EDITOR`/`VIEWER`/assigned `CLIENT_READONLY`)
  - query: `days` (`7..365`, default `30`)
  - behavior: returns off-page AEO score, sentiment totals, trend delta, top domains, actionable advice, and latest mentions

- `GET /api/v1/projects/{project_id}/monitoring/off-page-mentions/trends`
  - auth: authenticated project member (read access)
  - query: `days` (`7..365`, default `30`)
  - behavior: returns day-level trend points for off-page score and mention counts

- `GET /api/v1/projects/{project_id}/monitoring/off-page-mentions/feed`
  - auth: authenticated project member (read access)
  - query: `days`, `limit`, optional `sentiment`
  - behavior: returns mention-level feed rows with source domain, sentiment, authority score, linked keywords, and action recommendation

### Ingestion

- `POST /api/v1/projects/{project_id}/monitoring/off-page-mentions/ingest`
  - auth: authenticated project member with workspace write access (`ADMIN`/`EDITOR`)
  - body:
    - `source_type` (for example `manual_import`)
    - `mentions[]` rows with `snippet`, optional title/url/domain/published/sentiment metadata
    - `run_analysis` (default `true`)
    - `skip_existing` (default `true`)
  - behavior: persists deduplicated mention rows, runs batch NLP sentiment/entity analysis (with heuristic fallback when needed), and rebuilds daily summaries

## Embeddable Leads and Sitemap Batch Crawls

- plan gate: `lead_widget` (Specialist / Executive) for workspace lead widget operations
- all endpoints return `X-Request-ID`

### Public embed widget ingestion

- auth: embed key via `Authorization: Bearer stx_embed_*` or `X-Embed-Key: stx_embed_*`
- CORS: server validates `Origin` against `EmbedApiKey.allowed_origins`
- daily quota headers:
  - `X-RateLimit-Day-Limit`
  - `X-RateLimit-Day-Remaining`
  - `X-RateLimit-Day-Reset`
  - `Retry-After` on `429`

- `OPTIONS /api/v1/embed/audit`
  - behavior: preflight response with allow-origin/headers/methods for approved origins

- `POST /api/v1/embed/audit`
  - body: `{ "url": "https://example.com", "email": "lead@example.com", "entity"?: "Brand Name" }`
  - behavior: validates embed key + origin + daily quota + credits, creates `Lead` + queued `AuditJob` (`source=embed`)
  - returns: `202 Accepted` with `lead_id`, `job_id`, `poll_url`, `estimated_seconds`

- `OPTIONS /api/v1/embed/audit/{job_id}/status`
  - behavior: preflight response for widget polling route

- `GET /api/v1/embed/audit/{job_id}/status`
  - behavior: returns embed job status (`queued`/`running`/`completed`/`failed`), and completed scores when available
  - side effect: backfills linked `Lead.scores_json` and marks lead `audit_complete` when scores are resolved

### Workspace leads and embed key management

- auth: authenticated agency user (`portal_only` denied)
- access:
  - `GET` routes require workspace membership with non-portal role
  - `POST`/`DELETE` embed key routes require workspace write access (`ADMIN`/`EDITOR`)

- `GET /api/v1/workspaces/{workspace_id}/leads`
  - query: `skip`, `limit`, optional `status`
  - behavior: paginated workspace lead list with audit score snapshot metadata

- `GET /api/v1/workspaces/{workspace_id}/embed-keys`
  - behavior: lists workspace-scoped embed keys (hashed-at-rest credentials; raw key never returned)

- `POST /api/v1/workspaces/{workspace_id}/embed-keys`
  - body: `{ "label": "Homepage Widget", "allowed_origins": ["https://agency.com"], "daily_limit": 100 }`
  - behavior: creates a new active embed key and returns the raw key exactly once

- `DELETE /api/v1/workspaces/{workspace_id}/embed-keys/{embed_key_id}`
  - behavior: revokes embed key by setting `is_active=false`

### Project sitemap batch crawl

- auth: authenticated project member
- access:
  - estimate/start require workspace write access (`ADMIN`/`EDITOR`)
  - status/report allow project read access (`ADMIN`/`EDITOR`/`VIEWER`/assigned `CLIENT_READONLY`)

- `POST /api/v1/projects/{project_id}/sitemap-crawl/estimate`
  - body: `{ "sitemap_url": "https://example.com/sitemap.xml" }`
  - behavior: parses sitemap (index/nested/gzip supported, up to 500 URLs) and returns credit estimate

- `POST /api/v1/projects/{project_id}/sitemap-crawl`
  - body: `{ "sitemap_url": "https://example.com/sitemap.xml" }`
  - behavior: performs upfront credit precheck, creates `SitemapCrawlJob`, stages URLs in Redis, and dispatches bounded child audit jobs
  - returns: crawl `job_id`, initial status, discovered URL count, estimated credit cost

- `GET /api/v1/sitemap-crawl/{crawl_job_id}`
  - behavior: returns crawl counters/status (`total_urls`, `completed_urls`, `failed_urls`, `credits_consumed`, lifecycle timestamps)

- `GET /api/v1/sitemap-crawl/{crawl_job_id}/report`
  - behavior: returns aggregate sitemap report when status is `completed`; returns `409` until ready

### External error envelope

```json
{
  "error": {
    "code": "INSUFFICIENT_CREDITS",
    "message": "You need at least 3 credits to run a SMART audit. Current balance: 1.",
    "status": 402
  }
}
```

### Outbound webhooks

- supply `webhook_url` on create/bulk requests to receive a final callback
- callback header: `X-Qiko-Signal-Signature: sha256=<hex-digest>`
- retries: up to 3 attempts with persisted delivery status on the job row
- the one-time `webhook_secret` is returned only when the job is created

## File Uploads and Report Retention

- all endpoints return `X-Request-ID`

### Branding logo uploads

- `POST /api/v1/uploads/logo`
  - auth: authenticated agency user (`portal_only` denied)
  - plan gate: `has_white_label` (Executive)
  - query: `scope` (`workspace` or `user`, default `workspace`)
  - body: multipart file field `file`
  - validations:
    - allowed MIME types: `image/png`, `image/jpeg`, `image/svg+xml`, `image/webp`
    - max file size: `2MB`
    - extension and MIME consistency checks, plus basic SVG sanity check
  - behavior: stores logo through the storage service and returns:
    - `url` (public GCS URL or local fallback URL)
    - `object_uri` (`gs://...` or `local://...`)
    - `filename`, `content_type`, `size_bytes`, `storage`
  - failures:
    - `400` invalid format/empty payload
    - `402` plan lock
    - `413` file too large

- `GET /api/v1/uploads/logo/local/{object_path}`
  - auth: none (internal fallback serving route)
  - behavior: serves local fallback logo bytes for `local://` objects when GCS is not configured

### Complex report expiry and download behavior

- `GET /api/v1/reports/complex/{report_id}/status`
  - auth: authenticated agency user with report ownership access
  - behavior: returns report job status metadata including:
    - `status` (`queued`, `running`, `succeeded`, `failed`, `expired`)
    - `download_url` (only when `succeeded`)
    - `expired` (boolean)
    - `retention_days` (effective retention window)

- `GET /api/v1/reports/complex/{report_id}/download`
  - auth: authenticated agency user with report ownership access
  - behavior: resolves bytes from storage URI (`gs://` / `local://`) or legacy local path and returns PDF attachment
  - failures:
    - `409` when report is not ready
    - `410` when report is expired or file is no longer available

### Admin retention operations

- `GET /api/v1/admin/operations`
  - auth: admin (`get_current_admin_user`)
  - behavior: includes operational toggles plus `report_retention_days`

- `POST /api/v1/admin/operations/report-retention`
  - auth: admin (`get_current_admin_user`)
  - body: `{ "days": 30 | 60 | 90 }`
  - behavior: updates persisted report retention policy used by report status and `cron_sweeper.py` cleanup

## Project Entity Authority

- plan gate: `entity_authority` (Specialist / Executive)
- auth: authenticated project member (`ADMIN`/`EDITOR`/`VIEWER`/assigned `CLIENT_READONLY` for read endpoints)
- all endpoints return `X-Request-ID`

- `GET /api/v1/projects/{project_id}/entity-authority`
  - behavior: returns the latest persisted authority score and component breakdown; computes and persists an initial snapshot when none exists

- `GET /api/v1/projects/{project_id}/entity-graph`
  - behavior: returns aggregated project entity graph (`nodes`, `edges`, categories, URL mentions) plus missing target entities

- `GET /api/v1/projects/{project_id}/entity-authority/gaps`
  - behavior: returns missing target entities derived from `Project.icp_roles` + `Project.usp` compared against detected audit entities

- `GET /api/v1/projects/{project_id}/entity-authority/trend?limit=12`
  - behavior: returns historical authority snapshots (coverage/depth/consistency/uniqueness + counts)

- `POST /api/v1/projects/{project_id}/entity-authority/compute`
  - behavior: triggers recomputation and persists a fresh snapshot
  - access: requires workspace write role (`ADMIN` or `EDITOR`)

## Project CMS Fix Delivery

- push plan gate: `cms_push` (Executive)
- auth: authenticated project member; write routes require workspace write role (`ADMIN`/`EDITOR`)
- all endpoints return `X-Request-ID`

- `POST /api/v1/projects/{project_id}/cms/connect`
  - body: `{ "cms_type": "wordpress" | "shopify", "site_url": "...", "credentials": { ... } }`
  - behavior: creates or updates a project-scoped CMS connection with encrypted credentials at rest

- `GET /api/v1/projects/{project_id}/cms/connections`
  - behavior: lists project CMS connections with credential previews and verification metadata

- `POST /api/v1/projects/{project_id}/cms/connections/{connection_id}/verify`
  - behavior: executes adapter health check and updates connection status (`verified`/`error`)

- `DELETE /api/v1/projects/{project_id}/cms/connections/{connection_id}`
  - behavior: removes a project CMS connection

- `GET /api/v1/tasks/{task_id}/cms/preview`
  - query: `connection_id`, `page_url`, `field`, optional `new_value`
  - behavior: returns current/proposed values, rendered diff HTML, and a short-lived confirmation token

- `POST /api/v1/tasks/{task_id}/cms/push`
  - body: `{ "connection_id": ..., "page_url": "...", "field": "...", "confirmation_token": "...", "new_value"?: "..." }`
  - behavior: validates preview token, sets task `in_progress`, pushes through adapter, then marks task `done` on success and inserts immutable deployment log rows

- `POST /api/v1/tasks/{task_id}/cms/rollback`
  - body: `{ "connection_id": ..., "deployment_log_id"?: ... }`
  - behavior: replays previous value from latest successful deployment log, resets task to `todo` on success, and inserts immutable rollback log rows

- `GET /api/v1/projects/{project_id}/cms/deployment-log`
  - query: optional `task_id`, `connection_id`, `limit`
  - behavior: returns project-scoped CMS deployment history (`pushed`, `rolled_back`, `failed`)

## Project Signal Benchmarks

- plan gate: Specialist / Executive (same entitlement class as entity-authority)
- auth: authenticated project member (`ADMIN`/`EDITOR`/`VIEWER`/assigned `CLIENT_READONLY` for read endpoints)
- all endpoints return `X-Request-ID`

- `GET /api/v1/projects/{project_id}/benchmark?metric=geo_score`
  - behavior: returns project percentile context for the requested metric
  - response status:
    - `ok`: percentile/top-percent available
    - `insufficient_data`: cohort suppressed or sample thresholds not met
  - cohort suppression baseline: `k>=10 projects`, `>=3 workspaces`

- `GET /api/v1/projects/{project_id}/citation-stability`
  - behavior: returns the latest read-only `citation_stability` summary for the project
  - response includes value, confidence band, data point count, and component/weight breakdown

- `GET /api/v1/projects/{project_id}/remediation-impact`
  - behavior: returns the latest read-only `remediation_impact` summary for the project
  - response includes value, confidence band, data point count, and component/weight breakdown

- `GET /api/v1/projects/{project_id}/pipeline-quality`
  - behavior: returns the latest read-only `pipeline_quality` summary derived from V3 claim-disposition facts
  - response includes value, confidence band, data point count, per-pipeline breakdown, and score weights

- `GET /api/v1/projects/{project_id}/provider-cost-efficiency`
  - behavior: returns the latest read-only `provider_cost_efficiency` summary derived from V3 per-agent facts plus audit quality proxies
  - response includes value, confidence band, data point count, and component/weight breakdown

## Admin Signal Warehouse Operations

- auth: admin (`get_current_admin_user`)
- all endpoints return `X-Request-ID`

- `GET /api/v1/admin/signal-warehouse/health`
  - behavior: returns signal fact totals, historical audit coverage, backfill coverage %, and latest ingestion timestamp

- `POST /api/v1/admin/signal-warehouse/backfill`
  - body: `{ "dry_run": false }`
  - behavior: triggers replay-safe signal ingestion backfill and benchmark aggregate recompute
  - response: processing counts (`audits_processed`, `batches_processed`, `rows_inserted`, `cohort_rows_written`) and surfaced errors list

## Workspace White-Label & Tenant Branding

- plan gate: `has_white_label` (`plan_executive`)
- all workspace white-label routes require an authenticated agency user and return `402` when the current plan is not eligible

### Workspace branding settings

- `GET /api/v1/workspaces/current/white-label`
  - auth: authenticated agency user, denied for `portal_only`
  - behavior: returns the effective workspace branding payload plus persisted custom domains; the authenticated dashboard shell consumes this payload for workspace title, favicon, color-token, and powered-by resolution

- `PUT /api/v1/workspaces/current/white-label`
  - auth: authenticated agency user on an eligible plan
  - body:

```json
{
  "company_name": "Agency Analytics",
  "custom_logo_url": "https://cdn.example.com/logo.svg",
  "primary_color": "#14B8A6",
  "secondary_color": "#0EA5E9",
  "custom_favicon_url": "https://cdn.example.com/favicon.png",
  "custom_page_title": "Agency Audit Portal",
  "custom_meta_description": "Client-facing GEO and AEO reporting portal.",
  "hide_powered_by": true,
  "email_sender_name": "Agency Audit Team",
  "email_reply_to": "support@example.com",
  "social_linkedin_url": "https://linkedin.com/company/agency-analytics",
  "social_x_url": "https://x.com/agencyanalytics",
  "company_legal_name": "Agency Analytics SRL",
  "company_address": "42 Orbit Avenue\nBucharest, Romania",
  "company_trademark_text": "Agency Analytics is a trademark of Agency Analytics SRL.",
  "footer_about_url": "https://agency.example/about",
  "footer_blog_url": "https://agency.example/blog",
  "footer_support_url": "https://agency.example/support",
  "footer_legal_url": "https://agency.example/legal",
  "footer_preferences_url": "https://agency.example/preferences",
  "footer_privacy_url": "https://agency.example/privacy"
}
```

  - behavior: updates workspace-level branding and returns the refreshed payload

### Custom domain lifecycle

- `POST /api/v1/workspaces/current/white-label/domains`
  - auth: authenticated agency user on an eligible plan
  - body: `{ "domain": "audit.agencyname.com" }`
  - behavior: creates or updates a pending custom domain row and returns the full white-label settings payload including the expected `dns_target`

- `POST /api/v1/workspaces/current/white-label/domains/{domain_id}/verify`
  - auth: authenticated agency user on an eligible plan
  - behavior: checks DNS ownership, updates `verified`, `ssl_status`, `verification_error`, and may queue domain lifecycle notification emails
  - Cloudflare mode: when `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ZONE_ID` are configured, the same call also creates or refreshes the Cloudflare custom hostname and maps its activation state into `ssl_status`

- `DELETE /api/v1/workspaces/current/white-label/domains/{domain_id}`
  - auth: authenticated agency user on an eligible plan
  - behavior: removes a workspace-owned custom domain

### Workspace email footer settings

- `GET /api/v1/workspaces/current/email-footer`
  - auth: authenticated agency user, denied for `portal_only`
  - behavior: returns social/legal/company footer metadata currently configured for lifecycle email rendering

- `PATCH /api/v1/workspaces/current/email-footer`
  - auth: authenticated agency user with workspace write access
  - body: any subset of footer fields:
    - `social_facebook_url`, `social_x_url`, `social_instagram_url`, `social_linkedin_url`, `social_youtube_url`, `social_tiktok_url`
    - `company_address`, `company_legal_name`, `company_trademark_text`
    - `footer_about_url`, `footer_blog_url`, `footer_support_url`, `footer_legal_url`, `footer_preferences_url`, `footer_privacy_url`
  - behavior: updates only supplied keys and returns the refreshed footer payload

### Admin runtime settings and cost reporting

- DB-manageable runtime settings are resolved through a single configuration registry backed by `OperationalSetting.admin_settings_payload`
- bootstrap-only secrets such as JWT keys, Stripe secrets/webhook secrets, and `ADMIN_EMAILS` remain env/SSM sourced
- when `OperationalSetting.admin_settings_payload` is empty, DB-managed settings auto-seed once from env/SSM on the next successful boot

- `GET /api/v1/admin/settings`
  - auth: authenticated admin user
  - behavior: returns integration diagnostics, API key metadata, security checks, recommendations, `email_footer_defaults`, `currency_policy`, and `high_confidence_rollout`
  - `currency_policy` contract:
    - `canonical_cost_currency`: always `EUR`
    - `billing_catalog_currency`: always `EUR`
    - `reporting_display_currency`: `EUR` or `USD`
    - `manual_usd_per_eur`: required only when `reporting_display_currency=USD`
    - `rate_source`: `canonical_eur` or `manual_admin`
    - `updated_at`, `updated_by_user_id`
  - `high_confidence_rollout` contract:
    - `feature_key`: `audit_high_confidence_mode`
    - `is_enabled`: boolean
    - `rollout_percentage`: integer `0-100`
    - `updated_at`: nullable ISO timestamp
    - `source`: `default` or `feature_flag`

- `PATCH /api/v1/admin/settings`
  - auth: authenticated admin user
  - body: any subset of runtime metadata overrides, including:
    - `integrations`
    - `api_keys`
    - `email_footer_defaults`
    - `currency_policy`
    - `high_confidence_rollout`
  - `currency_policy` patch body:

```json
{
  "currency_policy": {
    "reporting_display_currency": "USD",
    "manual_usd_per_eur": 1.11
  }
}
```

  - behavior: validates that USD reporting always includes a manual rate, persists the normalized override into `OperationalSetting.admin_settings_payload`, stamps `updated_at` and `updated_by_user_id`, and returns the refreshed admin settings payload
  - `high_confidence_rollout` patch body:

```json
{
  "high_confidence_rollout": {
    "is_enabled": true,
    "rollout_percentage": 60
  }
}
```

  - behavior: upserts the dedicated `audit_high_confidence_mode` feature flag, so rollout can be disabled entirely or percentage-released without changing plan entitlements

- `GET /api/v1/admin/costs/summary`
- `GET /api/v1/admin/costs/daily`
- `GET /api/v1/admin/costs/by-model`
- `GET /api/v1/admin/costs/by-workspace`
- `GET /api/v1/admin/costs/by-user`
  - auth: authenticated admin user
  - query:
    - `requested_tier`: optional; supports `fast`, `smart`, `deep_judgment`, plus legacy aliases normalized by the backend
    - `debate_profile`: optional; for example `high_confidence`
  - behavior: all five cost routes apply the same requested-tier and debate-profile filters against persisted audit metadata, return `currency` plus `currency_policy`, and convert display values from canonical USD into USD only when the admin runtime settings carry a manual reporting override

### Tenant-aware branding discovery

- `GET /api/v1/tenants/current-branding`
  - auth: none
  - behavior: resolves the current host through the tenant middleware and returns branding only when the host maps to an active workspace custom domain

- `GET /api/v1/portal/branding`
  - auth: assigned `CLIENT_READONLY`
  - behavior: returns workspace branding for the active portal, including `custom_favicon_url`, `custom_page_title`, and `hide_powered_by`

### Legacy compatibility contract

- `GET /api/v1/users/me/branding`
- `PUT /api/v1/users/me/branding`
  - auth: authenticated agency user on an eligible plan
  - behavior: these routes now resolve to the current workspace branding when a workspace exists, with fallback to the historical user-level fields for non-workspace contexts

## Localized Report Export

- `POST /api/v1/reports/generate-complex`
  - auth: authenticated agency user
  - body:

```json
{
  "audit_ids": [123],
  "template_type": "Executive",
  "site_id": 45,
  "date_from": "2026-02-01T00:00:00.000Z",
  "date_to": "2026-03-01T23:59:59.999Z",
  "report_options": {
    "mode": "aggregated",
    "sections": ["overview", "geo", "seo", "aeo"],
    "report_kind": "project",
    "hide_credit_cost": true,
    "language": "ro"
  }
}
```

  - behavior: queues a localized complex-report PDF job; `report_options.language` defaults from the selected project or audit context when omitted
  - notes:
    - `project` exports require a project-backed, site-linked audit and use the selected audit's site history when `site_id` is omitted
    - `financial` exports require a project-backed audit
    - competitor trend exports require tracked competitor site selection
    - `date_from` / `date_to` can scope aggregated history exports
    - `hide_credit_cost=true` redacts cost, credit, and token disclosures from the exported PDF
  - returns: `report_id`, `status`, `template_type`, `generated_at`, `audit_count`, `download_url`

- `POST /api/v1/reports/white-label/pdf`
  - auth: authenticated agency user
  - body: `audit_id`, optional `agency_name`, `title`, `primary_color`, `secondary_color`, `report_date`, `logo_data_url`, `include_competitor_analysis`, `language`
  - behavior: queues an executive-style branding export using the same backend localization pipeline
  - notes:
    - `report_kind=project` is rejected on this route; project exports must use the complex report flow
    - competitor trend exports are rejected on this route because they require tracked competitor selection
  - returns: `report_id`, `status`, `poll_url`

- `GET /api/v1/reports/complex/{report_id}/status`
  - auth: authenticated agency user
  - behavior: returns queued/running/succeeded/failed status for a report job plus optional error detail and download URL

- `GET /api/v1/reports/complex/{report_id}/download`
  - auth: authenticated agency user
  - behavior: streams the generated localized PDF when the job has succeeded

- localization notes:
  - supported delivery languages: `en`, `es`, `fr`, `de`, `it`, `ro`, `nl`, `pt`, `pl`, `sv`, `ja`, `zh`
  - missing translation keys fall back to English
  - Japanese and Chinese exports use dedicated CJK PDF fonts in the backend renderer

## Billing Top-Ups

- `POST /api/v1/billing/top-up`
  - auth: authenticated agency user, denied for `portal_only`
  - body: `{ "credits": 100-2000 }`
  - behavior: creates a one-time Stripe Checkout session with dynamic `price_data`
  - returns `checkout_url`, `credits`, `price_eur`, and `price_cents`

## Billing Commitments

- `GET /api/v1/billing/commitment-tiers`
  - auth: authenticated agency user, denied for `portal_only`
  - behavior: returns commitment tier metadata, plan-lock state, and the current commitment snapshot if one exists

- `GET /api/v1/billing/commitment`
  - auth: authenticated agency user, denied for `portal_only`
  - behavior: returns the current commitment status, cycle usage, overage, and pending next-cycle change state

- `POST /api/v1/billing/commitment-checkout`
  - auth: authenticated `plan_specialist` / `plan_executive` agency user, denied for `portal_only`
  - body: `{ "tier": "growth" | "scale" | "enterprise" }`
  - behavior: creates a Stripe subscription checkout with a fixed commitment price plus the shared metered overage price

- `POST /api/v1/billing/commitment-cancel`
  - auth: authenticated agency user with an active commitment
  - behavior: sets `cancel_at_period_end=true` on the Stripe commitment subscription and returns the refreshed commitment status

- `POST /api/v1/billing/commitment-change`
  - auth: authenticated agency user with an active commitment
  - body: `{ "tier": "growth" | "scale" | "enterprise" }`
  - behavior: schedules the new fixed commitment tier for the next billing cycle without proration

- `GET /api/v1/admin/billing/commitments`
  - auth: admin
  - behavior: paginated commitment list with live usage, overage, pending tier changes, and renewal window

- `GET /api/v1/admin/billing/commitments/overview`
  - auth: admin
  - behavior: aggregate commitment MRR, active count, pending cancellations, average usage, and total overage credits

## Report Annotations

### Agency routes

- `GET /api/v1/audits/{audit_id}/annotations`
  - auth: `ADMIN`, `EDITOR`, `VIEWER`
  - query: `section_path`, `source_recommendation_key`, `visibility`, `page`, `per_page`
  - returns paginated top-level threads with nested replies
- `POST /api/v1/audits/{audit_id}/annotations`
  - auth: `ADMIN`, `EDITOR`
  - body: `section_path?`, `source_recommendation_key?`, `content`, `visibility`, `parent_id?`
  - creates a top-level annotation or one-level reply
- `PUT /api/v1/audits/{audit_id}/annotations/{annotation_id}`
  - auth: annotation author or workspace `ADMIN`
  - body: `content?`, `visibility?`
  - updates content and, for top-level threads, visibility
- `DELETE /api/v1/audits/{audit_id}/annotations/{annotation_id}`
  - auth: annotation author or workspace `ADMIN`
  - soft deletes the annotation

## Claim Review Queue

### Agency routes

- `GET /api/v1/audits/{audit_id}/review-queue`
  - auth: `ADMIN`, `EDITOR`, `VIEWER`, assigned `CLIENT_READONLY`
  - returns all Track B claims currently in the manual-review audit trail for that audit, joined with any saved manual decisions
- `POST /api/v1/audits/{audit_id}/claims/{claim_id}/review`
  - auth: `ADMIN`, `EDITOR`
  - body: `disposition` (`manually_approved` | `manually_refused`), `note?`
  - upserts the claim review decision, updates the persisted audit report inline, and reconciles Orchestra V3 claim-disposition signal counters
- `GET /api/v1/audits/{audit_id}/review-summary`
  - auth: `ADMIN`, `EDITOR`, `VIEWER`, assigned `CLIENT_READONLY`
  - returns aggregate pending/approved/refused counts plus the export-impact note for refused claims

### Portal routes

- `GET /api/v1/portal/projects/{project_id}/audits/{audit_id}/annotations`
  - auth: assigned `CLIENT_READONLY`
  - returns only `client_visible` threads
- `POST /api/v1/portal/projects/{project_id}/audits/{audit_id}/annotations`
  - auth: assigned `CLIENT_READONLY`
  - reply-only route for existing `client_visible` threads

## Response shape

Thread listing returns:

```json
{
  "items": [
    {
      "id": 1,
      "audit_id": 12,
      "project_id": 3,
      "user_id": 7,
      "user_display_name": "owner",
      "parent_id": null,
      "section_path": "prioritized_actions[0]",
      "source_recommendation_key": "technical:expand-comparison-pages:abc123def456",
      "content": "Client-ready rollout note.",
      "visibility": "client_visible",
      "is_deleted": false,
      "created_at": "2026-03-02T12:00:00+00:00",
      "updated_at": null,
      "can_edit": true,
      "can_delete": true,
      "replies": []
    }
  ],
  "page": 1,
  "per_page": 50,
  "total": 1,
  "has_more": false
}
```

## Monitoring routes

Project monitoring now exposes project-scoped AI visibility endpoints in addition to the existing keyword, SERP, and LLM traffic routes.

- `GET /api/v1/projects/{project_id}/monitoring/visibility-queries`
  - auth: project dashboard user with project access
  - returns configured queries plus plan entitlements
- `POST /api/v1/projects/{project_id}/monitoring/visibility-queries`
  - auth: project dashboard user with project access
  - body:

```json
{
  "query_text": "best payroll software for smb",
  "query_type": "aeo",
  "providers": ["google", "openai"]
}
```

- `PATCH /api/v1/projects/{project_id}/monitoring/visibility-queries/{query_id}`
  - updates providers, query type, or `is_active`
- `DELETE /api/v1/projects/{project_id}/monitoring/visibility-queries/{query_id}`
  - removes a configured visibility query
- `GET /api/v1/projects/{project_id}/monitoring/visibility-summary`
  - returns aggregate score, provider breakdown, and per-query provider statuses
- legacy AEO/GEO tracker notes may seed pending queries in the summary, but measured statuses and citation counts come only from real visibility runs
- `GET /api/v1/projects/{project_id}/monitoring/visibility-trends?days=30`
  - returns date-series points for project AI visibility history
- `GET /api/v1/projects/{project_id}/monitoring/visibility-comparative?days=30`
  - auth: project dashboard user with project access; requires the
    `has_competitor_analysis` capability (Specialist or higher), otherwise `402`
  - returns the project's own domain and every tracked competitor domain, each with
    per-engine stats, a daily trend series, share of voice, and `last_measured_at`
  - `last_measured_at` is the freshest measurement behind that domain's numbers, or
    `null` when the domain has never been measured; `null` is not a zero and not "now"
  - `competitors_last_measured_at` is the freshest measurement across the non-primary
    domains only, so the brand's own fresher run never stands in for it
  - `competitor_sweep_interval_seconds` is the plan's scheduled competitor cadence
    (weekly by default on the plans that include competitor analysis, `null` where
    competitor cells are on-demand only). It is the expected refresh interval a client
    compares `competitors_last_measured_at` against before calling a figure stale
  - scheduled competitor measurement runs on this slower clock than the project's own
    domain (SIGV2-1208), so competitor figures on this surface can legitimately be
    days older than the brand figure beside them
- `GET /api/v1/projects/{project_id}/monitoring/ai-search-volatility/summary?provider=all&days=30`
  - returns global AI volatility score, weather label, components, industry rows, and citation movers
- `GET /api/v1/projects/{project_id}/monitoring/ai-search-volatility/trends?provider=all&days=30`
  - returns date-series volatility points for project monitoring and timeline overlay correlation
- `GET /api/v1/volatility/public?provider=all&days=30`
  - public no-auth route returning pre-aggregated volatility dashboard payload (`available_providers`, `summary`, `trends`, `industry_matrix`, `citation_ledger`)
