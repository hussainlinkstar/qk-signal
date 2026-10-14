# Agentic Evidence-Gathering — Implementation Plan

> **Version:** 1.0
> **Prepared:** June 2026
> **Scope:** Add a bounded agentic (ReAct) layer to the audit pipeline for adaptive
> evidence collection and competitor discovery — without bypassing any grounding gate.

---

## Table of Contents

1. [Motivation & Principle](#1-motivation--principle)
2. [Where It Plugs In](#2-where-it-plugs-in)
3. [Architecture Components](#3-architecture-components)
4. [Phase 0 — Setup](#phase-0--setup)
5. [Phase 1 — ToolRegistry + Read-Only Wrappers](#phase-1--toolregistry--read-only-wrappers)
6. [Phase 2 — EvidenceAgent Loop (Shadow Mode)](#phase-2--evidenceagent-loop-shadow-mode)
7. [Phase 3 — Integration into perform_audit()](#phase-3--integration-into-perform_audit)
8. [Phase 4 — Progress Events](#phase-4--progress-events)
9. [Phase 5 — Competitor Agent](#phase-5--competitor-agent)
10. [Phase 6 — Validation & Rollout](#phase-6--validation--rollout)
11. [Constraints (from AGENTS.md)](#constraints-from-agentsmd)
12. [Risk Register](#risk-register)

---

## 1. Motivation & Principle

The current LLM pipeline is a **fixed multi-agent debate** (generator → critic →
synthesizer → judge, tier-gated). It is sophisticated but not *agentic*: the code decides
which steps run and in what order. The LLMs receive pre-gathered evidence (Firecrawl,
PageSpeed, sitemap) and produce structured JSON.

True agentic AI means a **bounded autonomous loop with tool use**: the model decides *which*
tools to call, *in what order*, and *when it is done* (ReAct / plan-act-observe-reflect).

**Core principle — the agent works BEFORE scoring, never in place of the gates.**
Everything the agent produces enters the pipeline as evidence in `context_payload` and
passes unchanged through `HallucinationService.analyze()` + `GroundingGateService.evaluate()`.
The agent may explore freely, but it cannot bypass a single gate. This resolves the tension
with the anti-hallucination guarantees in `AGENTS.md` (grounding rate >= 85%, domain
boundary = 0, `CanonicalAuditAnalysisContract` validation).

---

## 2. Where It Plugs In

The agent is inserted **only in Layer 1 (collection)**, as a new Stage 1.5 inside
`perform_audit()` (`audit_runner.py:1466`).

```
perform_audit() (audit_runner.py:1466)
│
├─ STAGE 1: scrape (scraper_service.get_page_content_and_screenshot)  ← evidence anchor
│
├─ STAGE 1.5: EVIDENCE AGENT (NEW) ─────────────────────────┐
│     bounded ReAct loop, whitelisted tools, read-only       │
│     adaptively decides what else to collect → produces      │
│     "augmented_evidence" (still deterministic / citable)    │
│                                                             │
├─ STAGE 2: deterministic signals (perf, network, schema) ───┘
│
├─ STAGE 3: ai_client.generate_audit()  ← receives augmented evidence in context_payload
│
├─ STAGE 4: HallucinationService.analyze()  ← UNCHANGED, validates everything
├─ STAGE 4: GroundingGateService.evaluate() ← UNCHANGED, drops hard-flagged findings
│
└─ STAGE 5: report assembly
```

If the agent brings in junk, the resulting findings score certainty < 0.15, get
hard-flagged, and are excluded. The system self-protects.

---

## 3. Architecture Components

### 3.1 EvidenceAgent (loop controller)

New file: `backend/services/agentic/evidence_agent.py`

```python
@dataclass
class AgentBudget:
    max_steps: int = 6              # hard cap on iterations
    max_tool_calls: int = 10
    max_wall_seconds: float = 25.0  # < tier timeout (fast=120s, smart=300s)
    max_extra_pages: int = 4
    max_cost_usd: float = 0.05      # enforced via ai_economics_ledger_service

class EvidenceAgent:
    def __init__(self, ai_client: AIClient, tools: ToolRegistry,
                 budget: AgentBudget, on_event: Callable | None):
        ...

    async def run(self, *, anchor: EvidenceAnchor, goal: str) -> AugmentedEvidence:
        # ReAct: plan -> act -> observe -> reflect, until stop or budget exhausted
```

Three hard constraints make the loop production-safe:

1. **Bounded** — `AgentBudget` caps steps / time / cost. No infinite loops. On exhaustion
   it returns what it gathered (graceful degradation, not an error).
2. **Decision = planning only, not final output.** The LLM picks *which tool* to call; it
   does not invent findings. Findings remain the job of Layer 3 + gates.
3. **All output is citable** — every evidence fragment carries `source_url` + `raw_excerpt`,
   so it is verifiable by `HallucinationService`.

### 3.2 ToolRegistry (strict whitelist)

New file: `backend/services/agentic/tools.py`. Each tool is a **read-only** wrapper over an
already-existing service — no new fetch logic.

| Tool | Wraps (existing) | Purpose |
|------|------------------|---------|
| `fetch_internal_page(url)` | `scraper_service.get_page_content_and_screenshot` | Crawl an additional internal page (e.g. thin content -> grab 3 internal pages) |
| `get_sitemap_urls()` | `sitemap_crawler_service` | URL list for smart selection |
| `check_schema(url)` | `aeo/structure_service.analyze_json_ld_structure` | Detect JSON-LD schema |
| `discover_competitors(...)` | `CompetitorDiscoveryService.discover_competitors` | Competitor identification |
| `fetch_serp(query)` | `provider_adapters.serpapi_provider` | Real SERP (not invented) |
| `get_performance(url)` | `performance_service.get_performance_metrics` | Core Web Vitals |

Registry rules (enforced in code, not in the prompt):
- Whitelist only. No `eval`, no arbitrary external URL fetch beyond target domain + SERP.
- Domain allowlist: `fetch_internal_page` accepts only URLs under the audited domain.
- Each call goes through the existing circuit breaker + `ai_economics_ledger_service` for cost.
- Results normalized to `EvidenceFragment`.

### 3.3 Output contract

New file: `backend/services/agentic/types.py`

```python
@dataclass
class EvidenceFragment:
    source_url: str          # required — for grounding
    kind: str                # "internal_page" | "schema" | "serp" | "competitor" | "cwv"
    raw_excerpt: str         # citable raw text
    signal_value: dict       # structured data (e.g. cwv numbers)
    confidence: float

@dataclass
class AugmentedEvidence:
    fragments: list[EvidenceFragment]
    agent_trace: list[dict]  # plan/act/observe for observability
    budget_used: AgentBudget
```

`fragments` are serialized into `context_payload["augmented_evidence"]` (Stage 3) AND the
`raw_excerpt` values are concatenated into the `source_content` passed to
`HallucinationService.analyze(source_content=...)`. Thus any finding based on agent-collected
evidence has an evidence anchor and is verifiable.

---

## Phase 0 — Setup

Zero risk, no business logic. Everything disabled.

| Task | File | Detail |
|------|------|--------|
| Branch | — | `git checkout -b feature/agentic-evidence` from updated `main` |
| Feature flag | `core/config.py` + admin config | `AGENTIC_EVIDENCE_ENABLED=false` (default off), runtime-editable |
| Package structure | `backend/services/agentic/__init__.py` | new directory |
| Agent config | `core/config.py` | `AGENTIC_MAX_STEPS`, `AGENTIC_MAX_WALL_SECONDS`, `AGENTIC_MAX_COST_USD`, `AGENTIC_TIERS=smart,deep_judgment` |

**Acceptance:** `ruff check` passes, flag readable from admin, audit behavior unchanged.

---

## Phase 1 — ToolRegistry + Read-Only Wrappers

Refactor, low risk. Tools exist, no loop yet.

| Task | File | Detail |
|------|------|--------|
| Dataclasses | `services/agentic/types.py` | `EvidenceFragment`, `AugmentedEvidence`, `AgentBudget` |
| Tool base + registry | `services/agentic/tools.py` | `Tool` protocol, `ToolRegistry` with whitelist + domain allowlist |
| Wrappers | `services/agentic/tools.py` | `fetch_internal_page`, `get_sitemap_urls`, `check_schema`, `discover_competitors`, `fetch_serp`, `get_performance` — each calls existing service and normalizes to `EvidenceFragment` |
| SSRF guard | `services/agentic/tools.py` | `fetch_internal_page` rejects URLs outside target domain |
| Tests | `tests/agentic/test_tools.py` | mock services, verify normalization + allowlist + external-domain rejection |

**Acceptance:** each tool returns `EvidenceFragment` with `source_url` + `raw_excerpt`;
domain allowlist test passes; `pytest tests/agentic` green.

---

## Phase 2 — EvidenceAgent Loop (Shadow Mode)

Bounded ReAct loop behind the flag, **log-only** (does not affect the report).

| Task | File | Detail |
|------|------|--------|
| Loop controller | `services/agentic/evidence_agent.py` | `EvidenceAgent.run()` — plan->act->observe->reflect, stop on done or budget |
| Budget enforcement | `services/agentic/evidence_agent.py` | hard caps: steps, wall time, tool calls, cost (via `ai_economics_ledger_service`) |
| Planner prompt | `prompts/agentic/evidence_planner.md` | LLM picks ONLY which tool to call (no findings); JSON output `{action, args}` or `{stop}` |
| Cost tracking | integrate `ai_economics_ledger_service` | cap $0.05/audit |
| Shadow mode | `evidence_agent.py` | if flag on but `shadow=true`: run, log `agent_trace`, do NOT return into pipeline |
| Tests | `tests/agentic/test_evidence_agent.py` | budget respected (loop stops), graceful timeout, robust planner JSON parse |

**Acceptance:** loop never exceeds budget (test with a mock that wants to loop forever); on
timeout returns what it gathered; zero report impact (shadow).

**Explicit stop / reflect criteria** (closes the "stop on done" ambiguity): the `reflect` step returns `{status: done|continue, reason}` and emits `{stop}` when (a) budget exhausted, (b) aggregate evidence confidence > 0.85 on required signals, OR (c) diminishing returns (last 2 calls < 5% new evidence). Each `EvidenceFragment.confidence` is set by the tool wrapper (direct match ~0.95, partial ~0.60); the reflect step compares the aggregate to a 0.70 threshold to decide whether to probe further.

---

## Phase 3 — Integration into perform_audit()

Agent evidence enters the pipeline AND the gates.

| Task | File | Detail |
|------|------|--------|
| Stage 1.5 hook | `audit_runner.py` (~after line 1710, post-scrape) | if flag on + tier in `AGENTIC_TIERS` -> `EvidenceAgent.run()` |
| Inject context | `audit_runner.py` (~line 2027, context_payload build) | add `context_payload["augmented_evidence"] = [...fragments]` |
| Feed gates | `audit_runner.py` (~line 2157) | concatenate `raw_excerpt` values into `source_content` sent to `HallucinationService.analyze()` |
| Fallback | `audit_runner.py` | flag off -> current code unchanged (zero behavior diff) |
| Integration tests | `tests/test_audit_runner_agentic.py` | finding based on fake fragment -> hard-flagged -> excluded (proof the gate protects) |

**Acceptance:** with flag off, output identical to today (snapshot test); with flag on,
fragments appear in `source_content` and the gate filters ungrounded findings.

---

## Phase 4 — Progress Events

| Task | File | Detail |
|------|------|--------|
| Emit events | `evidence_agent.py` + `services/audit_job_event_service.py` | map `agent_started->pipeline_started`, `agent_tool_called->step_started`, etc. |
| Normalize | `audit_job_event_service.py:normalize_debate_progress_event` | extend to accept new roles (`evidence_planner`, `tool:*`) |

**Acceptance:** `audit:job:{id}:events` stream contains agent steps; unmodified frontend
shows progress.

---

## Phase 5 — Competitor Agent

| Task | File | Detail |
|------|------|--------|
| Goal-driven discovery | `services/agentic/competitor_agent.py` | `goal="find+validate 3-5 competitors"`, reuse `discover_competitors`/`fetch_serp`/`fetch_internal_page` |
| Candidate validation | `competitor_agent.py` | confirm category via fetch before accepting; filter editorial titles (logic from `discovery_service`) |
| Integration | `audit_runner.py` (~line 1749) | replace fixed sequence with the agent (behind the same flag) |

**Acceptance:** competitors validated with `confidence > threshold`; fewer wasted calls vs
the fixed sequence when the first provider already suffices.

---

## Phase 6 — Validation & Rollout

| Task | Detail |
|------|--------|
| Shadow analysis | run shadow on **N=100** real audits (95% CI); compare grounding rate **per tier**, latency **p50/p95/p99**, cost distribution (mean / p95), finding-count delta vs. baseline |
| Quality gate | grounding rate **>= 85% per tier** (rule from `AGENTS.md`); p99 agent time < 25s; cost p95 < $0.045; hard-flagged findings delta <= 2%; otherwise do not enable |
| Observability | per-tool `ToolCallMetrics` (tool, latency_ms, in/out tokens, cost, status) logged to `ai_economics_ledger_service`; budget-utilisation queryable; deterministic snapshot test on 10 fixed URLs |
| Gradual rollout | enable on `smart`/`deep` for a pilot workspace -> monitor -> expand |
| Kill switch | flag stays runtime-editable; any issue -> off instantly, reverts to current pipeline |

---

## Constraints (from AGENTS.md)

- The agent does **not** bypass any gate; `CanonicalAuditAnalysisContract` stays intact.
- LLM calls go through the `ai-service` container via HTTP (`AIClient`), not `AIFactory`
  directly from routers.
- Active only on `smart`/`deep` — `fast` stays fast and deterministic.
- Local edit -> commit on branch -> PR (no self-merge), per the repo workflow.

---

## Risk Register

| Risk | Mitigation |
|------|------------|
| Infinite loop / cost runaway | `AgentBudget` hard caps (steps/time/cost), enforced by controller |
| Hallucination | Output mandatorily passes existing gates; no exceptions |
| Variable latency | `max_wall_seconds=25` < tier timeout; agent active only on `smart`/`deep`, NOT `fast` |
| SSRF / arbitrary fetch | Domain allowlist + tool whitelist |
| Core audit regression | Feature flag `AGENTIC_EVIDENCE_ENABLED` (runtime admin config); fallback = current pipeline unchanged |
