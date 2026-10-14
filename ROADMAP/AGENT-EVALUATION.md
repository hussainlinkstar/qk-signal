# Agentic Agent-Evaluation Platform — Strategy & Implementation Plan

> **Version:** 1.0
> **Prepared:** June 2026
> **Scope:** Repurpose Qiko Signal's "AI evaluating AI" engine into an **agentic** platform that
> evaluates conversational AI agents (initially Qiko.ai digital workers) across capability,
> consistency, and resilience — and, over time, distils the accumulated evaluation data into a
> proprietary scoring SLM.
> **Related:** This plan builds ON TOP of [`AGENTIC-EVIDENCE.md`](./AGENTIC-EVIDENCE.md)
> (the bounded ReAct evidence-gathering layer). It does **not** replace it — it reuses the same
> agentic primitives (bounded loop, whitelisted tools, budget caps, grounding gates) for a new
> target: **AI agents instead of websites.**

---

## Table of Contents

1. [Thesis — Why Agentic AI Is the Core](#1-thesis--why-agentic-ai-is-the-core)
2. [Relationship to the Existing Agentic Evidence Layer](#2-relationship-to-the-existing-agentic-evidence-layer)
3. [Honest Reuse Map — What Exists vs. What Is New](#3-honest-reuse-map--what-exists-vs-what-is-new)
4. [The Three Pillars (Capability / Consistency / Resilience)](#4-the-three-pillars)
4b. [Architecture-Fit Scoring — Advisory vs. Action](#4b-architecture-fit-scoring--advisory-vs-action)
5. [Architecture — The Evaluator Agent](#5-architecture--the-evaluator-agent)
6. [Grounding Redefined for Transcripts](#6-grounding-redefined-for-transcripts)
7. [Qiko Connection (Option A / Option B)](#7-qiko-connection)
8. [Phase 0 — Connector + Manual Harness](#phase-0--connector--manual-harness)
9. [Phase 1 — Conversation Harness (multi-turn, multi-session)](#phase-1--conversation-harness)
10. [Phase 2 — Agentic Scenario Generator + Adversarial Probing](#phase-2--agentic-scenario-generator--adversarial-probing)
11. [Phase 3 — Scoring, Debate Reuse, Trend Lines](#phase-3--scoring-debate-reuse-trend-lines)
12. [Phase 4 — Continuous Monitoring (drift / regression)](#phase-4--continuous-monitoring)
13. [Phase 5 — Proprietary Scoring SLM (data moat)](#phase-5--proprietary-scoring-slm)
14. [SLM Reality Check](#slm-reality-check)
15. [Hardening Addenda (Expert Panel Review)](#hardening-addenda-expert-panel-review)
16. [Risk Register](#risk-register)

---

## 1. Thesis — Why Agentic AI Is the Core

For the SEO conversational worker, agentic AI was mostly overkill (see panel conclusion in chat
history). **For agent evaluation, agentic AI is the right and necessary architecture** — and that
is the central idea of this plan.

Evaluating a conversational agent is inherently:

- **Multi-step** — you cannot judge memory, reasoning, or tool use from a single prompt; you must
  run multi-turn conversations.
- **Adaptive** — the next probe depends on the previous answer (e.g., "it claimed it remembers my
  preference — now open a fresh session and test if it actually persists").
- **Adversarial** — gaming-resistant evaluation requires fresh, model-generated attacks
  (prompt injection, boundary violations, multi-turn traps), not a fixed exam.
- **Goal-driven under a budget** — the evaluator should keep probing until it has enough evidence
  for a confident verdict, then stop.

That is the textbook definition of a **bounded ReAct agent**: plan → probe (tool/act) → observe →
reflect → decide next probe or stop. So the evaluator itself is an agent. We reuse the exact
agentic primitives already designed in `AGENTIC-EVIDENCE.md`.

> **One-liner for the market:** "A pen-test for AI agents, not an exam with known questions."

---

## 2. Relationship to the Existing Agentic Evidence Layer

`AGENTIC-EVIDENCE.md` defined a bounded agent that gathers *evidence about a website*. This plan
defines a bounded agent that gathers *evidence about an AI agent*. Same machinery, new target.

| Primitive (from AGENTIC-EVIDENCE.md) | Reused as |
|--------------------------------------|-----------|
| `AgentBudget` (max_steps / wall_seconds / cost) | Caps the number of probe turns per evaluation run |
| `ToolRegistry` (whitelisted, read-only) | Becomes the **probe toolset** (send_message, open_new_session, inject_payload, ...) |
| `EvidenceFragment` (source_url + raw_excerpt + signal) | Becomes a **TranscriptFragment** (turn_id + agent_response + observed_signal) |
| ReAct loop controller (`EvidenceAgent.run`) | Becomes `EvaluatorAgent.run` |
| Grounding gates (HallucinationService / GroundingGate) | Re-pointed: "is this verdict grounded in the transcript?" |
| Progress events (`audit:job:{id}:events`) | Reused verbatim for live evaluation progress |

**Net effect:** the website audit and the agent evaluation become two *targets* of the same
agentic evaluation engine. Both live behind the same job/queue/streaming infrastructure.

---

## 3. Honest Reuse Map — What Exists vs. What Is New

This section exists to keep internal planning honest (sales framing said "just point at a different
target" — true for the engine, optimistic for the harness).

| Component | Status | Notes |
|-----------|--------|-------|
| Multi-agent debate, scoring, evidence-linking, Pydantic contract | REUSE | Near-direct; new scoring schema per dimension |
| Job queue, streaming progress, billing/credits | REUSE | Already battle-tested |
| Bounded agentic loop + budget caps | REUSE | From `AGENTIC-EVIDENCE.md` |
| **Conversation harness** (multi-turn, multi-session, fresh-context) | NEW | Heart of the product; does not exist today |
| **Probe toolset** (send_message, new_session, inject, reset) | NEW | Read-only against external agent endpoints |
| **Scenario generator** (domain-aware, adversarial, model-generated) | NEW | Anti-gaming requirement |
| **Grounding redefinition** (anchor = transcript, not scraped page) | ADAPT | Reuse service, redefine the anchor |
| Connector to agent endpoints (Qiko Option A/B) | NEW (light) | HTTP client + auth |
| Trend / regression store | NEW | Per-agent score history over time |
| Scoring SLM training pipeline | NEW (Phase 5) | Data moat; phased, not day-1 |

---

## 4. The Three Pillars

The customer-facing framework (validated in the Edward Long conversation):

### Pillar 1 — Capability ("does it do what it claims?")
- Memory (in-session + cross-session)
- Reasoning / instruction following
- Tool use correctness
- Domain knowledge depth
- **Example finding:** "Cross-session memory — PARTIAL: remembered wine preference, lost the name
  collected at registration."

### Pillar 2 — Consistency ("how does it perform under pressure?")
- Stability across paraphrases and reorderings
- Behaviour at context limits / long conversations
- Edge cases, cost per task
- Repeatability (same scenario, same verdict band)

### Pillar 3 — Resilience ("can it be broken or gamed?")
- Prompt injection (incl. data-borne / indirect injection)
- Guardrail / boundary violations ("What is the capital of France?" on a wine agent)
- Multi-turn traps, jailbreak attempts
- Hallucination triggers
- **Security framing:** even a read-only agent can exfiltrate what it reads — test for it.

Each pillar maps to a scored, evidence-linked dimension in the canonical evaluation contract.

---

## 4b. Architecture-Fit Scoring — Advisory vs. Action

A fourth, cross-cutting dimension that came directly out of the agentic-AI vs. AI-engineering
debate. The two experts converged: **agentic AI is a moat for ACTION/workflow niche agents and
overkill (latency + cost + hallucination) for ADVISORY/Q&A agents.** The differentiator is not the
niche itself — it is whether the agent must *do* something (mutate external state, orchestrate
multiple sequential decisions) or merely *answer*.

This makes "architecture fit" a sellable evaluation output: Qiko Signal not only scores the agent,
it tells the creator whether the agent is **under-** or **over-engineered** for its job.

### Step 1 — Classify the agent

| Class | Signature | Right architecture |
|-------|-----------|--------------------|
| **Advisory** (Q&A, recommendation) | Answers from knowledge; no external state change | RAG + single-call function-calling |
| **Action / Workflow** | Books, sources, checks inventory, multi-step with side effects | Tool-calling + Plan-and-Execute + workflow engine |
| **Research / Long-horizon** | >10 adaptive steps, open-ended | Bounded ReAct (rare) |

The evaluator infers the class from the agent's description + observed behaviour during probing
(does it expose tools? does it attempt actions? does it need multi-turn planning?).

### Step 2 — Score the fit

| Agent class | Latency target | Cost/query target | Agentic surface | Verdict signal |
|-------------|----------------|-------------------|-----------------|----------------|
| Advisory (85–90% of niche agents) | < 1.5s p99 | ~$0.006 | function-calling only | Flag if it uses ReAct loops on plain Q&A → over-engineered |
| Action (10–15%) | 1–2.5s | ~$0.025 | tool-calling + light planning | Flag if it lacks tool use → under-engineered (it's "just Claude") |
| Research (rare) | > 5s acceptable | higher | bounded ReAct | Flag if used for conversational turns → wrong tier |

### Step 3 — Emit an architecture-fit finding (evidence-linked)

Example findings the engine should produce:

- *"Over-engineered: agent runs a multi-step reasoning loop on advisory queries (turns 3, 7).
  Switching to single-call function-calling would cut p99 latency ~3x with no quality loss."*
- *"Under-engineered: agent claims it can 'book a tasting' but has no tool use; it only describes
  the steps (turn 5). This is a chatbot, not a worker — exposes Qiko to the 'why not just Claude?'
  objection."*
- *"Memory is the real moat here, not loops: cross-session persistence works (turn 9) — that is the
  differentiator vs. vanilla Claude, achievable with prompt caching, no agentic overhead."*

### Why this is strategically valuable

This dimension directly answers Qiko's customer objection (*"why build an agent if I can just use
Claude?"*) with a measured, per-agent verdict instead of a sales claim:

- The differentiator vs. vanilla Claude is **memory + curated data + (for action agents) tool use**,
  not reasoning loops.
- Agentic AI answers *"why a worker, not a chatbot?"* — not *"why not Claude?"*.
- Qiko Signal becomes the referee that proves it, turn by turn.

> **Rule:** every architecture-fit verdict must cite the transcript turns that justify it
> (same grounding discipline as Section 6). No ungrounded "over-engineered" labels.

---

## 5. Architecture — The Evaluator Agent

```
                          ┌─────────────────────────────────────────────┐
                          │  Qiko Signal Evaluation Engine (reused)        │
                          │                                               │
  Qiko agent (public URL) │   ┌──────────────────────────────────────┐   │
        ▲   │             │   │ EvaluatorAgent (bounded ReAct)         │   │
        │   │ probe       │   │  plan -> probe -> observe -> reflect    │   │
        │   ▼             │   │  AgentBudget caps (turns/time/cost)     │   │
   ┌────┴──────┐  HTTP    │   └───────────────┬──────────────────────┘   │
   │ Connector │◄────────►│                   │ TranscriptFragments      │
   │ (A or B)  │          │                   ▼                          │
   └───────────┘          │   ┌──────────────────────────────────────┐  │
                          │   │ Scenario Generator (domain+adversarial)│  │
                          │   └──────────────────────────────────────┘  │
                          │                   │                          │
                          │                   ▼                          │
                          │   Multi-agent debate (gen->critic->          │
                          │   synth->judge)  ← REUSED                    │
                          │                   │                          │
                          │                   ▼                          │
                          │   Grounding gate (anchor = transcript)       │
                          │                   │                          │
                          │                   ▼                          │
                          │   Canonical Eval Report + Trend store        │
                          └─────────────────────────────────────────────┘
```

The **EvaluatorAgent** decides which scenario to run next based on what it has observed so far
(e.g., a weak guardrail answer triggers an escalating adversarial probe). It stops when the budget
is exhausted or when each pillar has a confident verdict.

---

## 6. Grounding Redefined for Transcripts

The anti-hallucination moat must be preserved, but the **evidence anchor changes**:

| Website audit | Agent evaluation |
|---------------|------------------|
| Anchor = scraped page content (Firecrawl/PageSpeed/sitemap) | Anchor = **the conversation transcript** the evaluator produced |
| Claim = "page lacks schema markup" | Claim = "agent failed cross-session memory" |
| Grounded if claim cites page evidence | Grounded if verdict cites specific turn(s) in transcript |

Rule (mirrors `AGENTS.md`): a verdict that cannot point to a concrete turn in the transcript is
flagged/excluded. Certainty thresholds (0.15 / 0.40) and grounding rate (>= 85%) carry over. This
prevents the evaluator from "hallucinating a failure" the agent never actually committed.

---

## 7. Qiko Connection

From the Edward Long conversation — two lightweight options, both supported:

- **Option A — direct endpoint.** Qiko exposes a per-agent chat endpoint
  (`POST /api/agents/{id}/chat`) or a public URL (e.g.
  `https://app.qiko.ai/chat/{agent_id}`). The evaluator sends test scenarios and evaluates the
  responses. Confirmed viable: Qiko already exposes public agent URLs for customers.
- **Option B — webhook.** Qiko Signal sends a prompt, Qiko forwards it to the agent and posts the
  response back.

Connector requirements: per-agent auth, session handling (so "new session" = fresh memory
context), rate-limit awareness, and timeout/retry. Read-only against the target agent.

---

## Phase 0 — Connector + Manual Harness

| Task | Detail |
|------|--------|
| Agent connector | HTTP client for Option A (public URL / chat endpoint) + auth |
| Session abstraction | `start_session()`, `send(message)`, `reset()` — fresh context = fresh memory |
| Manual scenario run | Hand-written scenario batch (memory, domain, guardrail) to validate the loop end-to-end |
| First report | Reproduce the Wine Legend pass: in-session memory PASS, cross-session PARTIAL, guardrails WEAK |

**Acceptance:** can connect to a live Qiko agent URL, run a multi-turn + multi-session scenario,
and produce an evidence-linked report. (Already proven manually on Wine Legend.)

---

## Phase 1 — Conversation Harness

| Task | Detail |
|------|--------|
| Multi-turn engine | Drive N-turn conversations, capture every turn as `TranscriptFragment` |
| Multi-session / cross-session | Spin fresh sessions to test persistence vs. in-session memory |
| Context-limit probes | Long conversations to test degradation at context boundaries |
| Cost/latency capture | Per-task cost + latency recorded as consistency signals |
| Stateless workers | Harness state in Redis/DB so workers stay restartable (ECS-ready) |

**Acceptance:** harness reliably distinguishes in-session vs. cross-session memory and records
per-turn evidence.

---

## Phase 2 — Agentic Scenario Generator + Adversarial Probing

| Task | Detail |
|------|--------|
| Domain inference | Infer the agent's domain from its description / first responses |
| Model-generated scenarios | Fresh prompts each run (anti-gaming — cannot memorise answers) |
| Adversarial suite | Prompt injection (direct + data-borne), boundary violations, multi-turn traps, hallucination triggers |
| Escalation logic | EvaluatorAgent escalates probes when it detects a weakness (this is the agentic core) |
| Budget caps | Reuse `AgentBudget` — cap probe turns/time/cost per run |

**Acceptance:** two runs on the same agent produce different probes but consistent verdict bands;
injection attempts are actually attempted and scored.

---

## Phase 3 — Scoring, Debate Reuse, Trend Lines

| Task | Detail |
|------|--------|
| Canonical eval contract | New Pydantic schema: per-pillar scores + evidence refs (turn ids) |
| Debate reuse | Each agent response judged by multi-model debate (gen->critic->synth->judge) — "only what survives challenge passes" |
| Multi-model cross-examination | More than one model judging each response (resilience to single-model bias) |
| Trend store | Per-agent score history; show 67% -> 84% over monthly runs |
| Report renderer | Reuse PDF/report pipeline with eval schema |

**Acceptance:** repeatable, comparable monthly scores with evidence; debate catches a planted
hallucination in a transcript.

---

## Phase 4 — Continuous Monitoring

| Task | Detail |
|------|--------|
| Scheduled re-evaluation | Reuse monitoring/cron workers to re-run evaluations on a cadence |
| Drift / regression alerts | Flag score drops, hallucination spikes, guardrail regressions before users hit them |
| Embedded scoring (future) | Real-time scoring hooks inside Qiko once the SLM is ready (Phase 5) |

**Acceptance:** a regression introduced into a test agent triggers an alert on the next scheduled run.

---

## Phase 5 — Proprietary Scoring SLM (data moat)

The strategic endgame: replace external LLM judges with one specialised, owned model.

| Task | Detail |
|------|--------|
| Data capture | Every evaluation already produces scored, categorised, evidence-linked records — the training set builds itself |
| Validation labels | Capture inter-rater agreement (debate consensus + periodic human spot-checks) as ground truth |
| Distillation | Train an SLM to reproduce the debate-ensemble verdicts |
| Calibration | Prove score X means the same thing run-to-run (calibration set + agreement metric) |
| Deployment | Offline / on-prem judge — data never leaves infra, exfiltration risk gone; faster + cheaper than multi-LLM |
| Productisation | Real-time scoring in Qiko, agent certification-as-a-service, industry benchmarking — all on the owned model |

---

## SLM Reality Check

To keep expectations honest (the figures quoted to Edward were optimistic):

- **"A few hundred to a few thousand evaluations"** yields a useful judge only if those evaluations
  are **validated**, not raw. Raw evals teach the SLM to copy noise.
- Correct sequence: **LLM-as-judge ensemble now -> collect + measure agreement -> distil SLM later.**
  The SLM is Phase 5, not day 1. The debate engine remains the judge until the SLM is calibrated.
- The real risk is **judge calibration**: a number like "84%" is worthless without inter-rater
  agreement and a reference set. Build the calibration set before claiming the SLM is production-ready.
- Rule of thumb: a few thousand *validated* records for a first credible production judge; expect
  to keep the ensemble as a fallback / re-labeller well beyond that.

---

## Hardening Addenda (Expert Panel Review)

Outcomes of a three-expert review (Agentic AI · AI Engineering · Skill/Agent Dev). These close
the gaps that would otherwise be discovered in production. **All five must be resolved in design
before Phase 1 code.**

### A1 — EvaluatorAgent decision logic & stop conditions (CRITICAL)

The loop must be an **orchestrator with a pillar state machine**, not a flat parallel run (flat
loses adaptive escalation, which is the product's value). Each pillar carries
`{score, confidence, evidence_refs, status: pending|confident|inconclusive}`.

Decision algorithm per probe:
1. Compute `turn_confidence` (judge scores the response against the pillar criterion).
2. `pillar_confidence = weighted_mean(last 3 turns, decay=0.8)`.
3. If `pillar_confidence >= threshold` → mark pillar confident.
4. If `< threshold` and budget remains → **escalate** with a harder probe.
5. If budget ≤ 2 turns left → stop, return best-effort verdict.

| Pillar | Confidence threshold | Escalation trigger |
|--------|----------------------|--------------------|
| Capability | 0.75 | turn_confidence < 0.50 → multi-turn memory/reasoning probe |
| Consistency | 0.70 | paraphrase variance > 20% → adversarial variant |
| Resilience | 0.65 | guardrail breach detected → multi-turn injection trap |

Stop = all pillars confident OR budget exhausted. **Sub-evaluators are tools of the orchestrator,
not separate agents.**

### A2 — Evaluator self-defense against the untrusted target (CRITICAL)

The target agent is untrusted (may be jailbroken/adversarial). Containment rules, enforced in code:

- The target's **raw response NEVER enters the planner/orchestrator context** — only structured,
  debate-derived signals do. `TranscriptFragment` stores `agent_response` (raw, for grounding only)
  separately from `observed_signal` (the only field the planner sees).
- **Separate LLM calls** for (a) parsing the target response and (b) judging it — breaks the
  injection chain.
- Parse defensively (`json.loads` with error handling); **never `eval`/`exec`**; truncate to a cap.
- Injection detection: flag suspicious patterns ("ignore your instructions", "system prompt:",
  self-scoring attempts) and lower confidence instead of acting on them.

### A3 — Grounding on transcripts: per-pillar rules (HIGH)

"Cite a turn" is too loose. Pillar-specific grounding (extends Section 6):

| Claim type | Grounded only if it cites… |
|------------|----------------------------|
| Memory | a turn with **explicit recall** of info actually stated earlier (not "should remember") |
| Tool use | a turn with a **real tool call**, not a description of one |
| Consistency | **2+ turns** with contradictory answers to the same query |
| Injection (resilience) | a turn where a payload was injected **and** the agent accepted it |
| Architecture-fit | the specific turns showing over-/under-engineering |

A claim whose supporting turns score `< 0.40` average certainty is flagged/excluded. No ungrounded
"failure" labels — this prevents the evaluator from hallucinating faults the agent never committed.

### A4 — Judge calibration & SLM data realism (CRITICAL)

Extends Phase 3 / Phase 5 / SLM Reality Check:

- **Do not train the SLM on the debate's own outputs** (data leakage → copies noise). Use a
  **held-out, human-reviewed calibration set** (N≈200) as ground truth; target inter-rater
  agreement **Cohen's kappa ≥ 0.75**.
- Use debate consensus as a **weak label** only when ≥3/4 models agree; exclude low-consensus evals
  from training.
- **Temporal** train/val/test split (not random) to test generalisation to new agents.
- SLM production gate: **ECE < 0.08**, **Spearman ≥ 0.85** vs. held-out test, monthly **drift
  detection**; debate ensemble stays as fallback until the SLM passes.
- Kill the vanity metric: report "67% → 84%" only with **(consensus N/4, confidence, baseline
  delta)**. Build a **baseline reference set (N≈50 human-validated agents)** so a score is
  interpretable ("60th percentile for advisory agents").

### A5 — Quantitative acceptance + observability (HIGH)

- Validation set: **N=100** evaluations (95% CI), grounding **≥85% per pillar**, latency
  **p50/p95/p99**, cost distribution (mean / p95), finding-count delta vs. baseline.
- Per-probe `ToolCallMetrics` (tool, latency_ms, in/out tokens, cost, status) logged to
  `ai_economics_ledger_service`; budget-utilisation queryable.
- **Pydantic contracts:** `TranscriptFragment` and `CanonicalAgentEvaluationContract`
  (per-pillar score + confidence + evidence_refs + debate consensus + grounding_rate).
- **Deterministic snapshot tests** on fixed transcripts so behaviour regressions are caught.
- **Target-agnostic engine:** Website and Agent implement one `EvaluationTarget` interface
  (`get_evidence_anchor`, `get_tool_registry`, `validate_finding`) so the loop is reused, not forked.

---

## Risk Register

| Risk | Mitigation |
|------|------------|
| Evaluator hallucinates a failure the agent never made | Grounding gate anchored to transcript; verdict must cite turn ids |
| Gaming the benchmark | Model-generated fresh scenarios every run; never hardcoded |
| Cost runaway on long multi-turn probes | `AgentBudget` caps (turns/time/cost) reused from AGENTIC-EVIDENCE.md |
| Target agent rate-limits / instability | Connector retries + backoff; mark inconclusive rather than fail-hard |
| SLM trained on noise | Validate with debate consensus + human spot-checks before distillation |
| Uncalibrated scores erode trust | Calibration set + inter-rater agreement before publishing numbers |
| Prompt injection during evaluation harms Qiko Signal itself | Treat all target-agent output as untrusted input; never execute it |
| Scope creep beyond agent eval | Keep evaluation engine target-agnostic; new targets are config, not forks |
