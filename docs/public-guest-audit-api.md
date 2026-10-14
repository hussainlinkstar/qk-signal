# Public guest audit API (SIGNAL-1041)

The contract the marketing site (`qiko-website-v2`, which owns `/signal/guest-audit`)
calls to run a free audit for a visitor with no account.

Signal's own legacy `POST /api/v1/guest-audit` is a different, synchronous endpoint used
by Signal's own marketing page. It is unchanged and is not this contract.

## Why it is two calls

An audit takes tens of seconds. `POST /api/v1/audit` has been observed returning 502 from
Cloudflare while the audit completed successfully server side, so a single blocking call
gives the browser an error for work that already ran and was paid for. The public path is
therefore submit plus poll.

## 1. Submit

```
POST /api/v1/public/guest-audit
Content-Type: application/json
```

Body (unknown fields are rejected with 422):

| Field | Type | Required | Notes |
|---|---|---|---|
| `audit_target_type` | `"website"` \| `"brand"` | no, defaults to `website` | |
| `url` | string | required when `audit_target_type` is `website` | must be a public `http(s)` URL |
| `target_name` | string | required when `audit_target_type` is `brand` | 1 to 256 characters |
| `target_metadata` | object | no | at most 20 keys |
| `email` | string | no | if present, the follow-up email is queued as today |

`202 Accepted`:

```json
{
  "job_id": "0f3c...",
  "status": "queued",
  "poll_url": "/api/v1/public/guest-audit/0f3c...",
  "poll_after_ms": 3000,
  "expires_in_seconds": 1800,
  "deduplicated": false
}
```

`deduplicated: true` means an audit for the same target was already running and this
submission joined it rather than paying for a second identical run.

Errors:

| Status | When | Body |
|---|---|---|
| 400 | the URL is malformed, or resolves to a private, loopback, link-local or reserved address | `{"detail": "..."}` |
| 422 | the body is otherwise invalid (unknown field, missing `target_name`, and so on) | FastAPI validation shape |
| 429 | per-IP submit limit exhausted | `{"detail": "..."}`, `Retry-After` |
| 503 | the queue is at its depth ceiling, or Redis is unavailable | `{"detail": "..."}`, `Retry-After` |

The 400 message is deliberately identical for a malformed URL and for a private address,
so the endpoint cannot be used to probe Signal's internal network.

## 2. Poll

```
GET /api/v1/public/guest-audit/{job_id}
```

```json
{ "job_id": "0f3c...", "status": "queued", "poll_after_ms": 3000 }
{ "job_id": "0f3c...", "status": "running", "poll_after_ms": 3000 }
{ "job_id": "0f3c...", "status": "failed", "poll_after_ms": 0,
  "error": { "code": "timeout", "message": "The audit took too long to complete. Please try again." } }
{ "job_id": "0f3c...", "status": "completed", "poll_after_ms": 0, "result": { } }
```

`status` is always one of `queued`, `running`, `completed`, `failed`. Poll again after
`poll_after_ms`; it is `0` on a terminal status. `error.code` is one of `target_blocked`,
`timeout`, `internal_error`. A `404` means the job id is unknown or the job has aged out
past its TTL; both answer the same way on purpose.

`GET` responses are `Cache-Control: no-store`.

## 3. The result

Everything an anonymous caller receives is an explicit allowlist, projected field by field
in `backend/services/guest_audit_public.py`. A full guest payload contains considerably
more than this.

```json
{
  "schema_version": "guest-audit-public/2",
  "generated_at": "2026-09-09T10:00:00+00:00Z",
  "target": { "type": "website", "name": "Example", "url": "https://example.com" },
  "scores": { "overall": 61, "seo": 70, "aio": 57 },
  "score_groups": [ { "label": "SEO Health", "score": 70, "locked": false } ],
  "summary": "Solid basics, weak answer formatting.",
  "insights": ["Performance is solid, but there is room for optimization."],
  "aio_insights": [
    "Missing FAQ schema. The pricing page has no FAQPage structured data.",
    "Weak entity grounding"
  ],
  "recommendations": [
    { "priority": "Critical", "title": "Missing meta description",
      "description": "Reduces click-through rate." }
  ],
  "locked_sections": {
    "geo": { "is_locked": true, "required_plan_label": "Specialist",
             "detail": "4 GEO findings discovered. Sign up to see the full breakdown." }
  },
  "degradation": {
    "fully_measured": false,
    "javascript_rendered": false,
    "ai_analysis_available": true,
    "reasons": [ { "code": "javascript_not_rendered", "message": "..." } ]
  },
  "claim_token": "eyJ..."
}
```

Deliberately **not** exposed: raw PageSpeed audits and the whole `performance` block,
network protocol diagnostics, raw model findings (`structured_findings`, `analysis`),
entity and competitor lists, the hallucination block, the tool and model names in
`analysis_metadata`, per-dimension score breakdowns, the internal `request_id`, the
internal gating identifiers (`capability_key`, `required_plan`, `lock_origin`), and the
`implementation` step by step fix on each recommendation, which is the paid product.

`claim_token` is the existing guest claim token: send the visitor to
`/register?guest_audit_token=<claim_token>` to attach the audit to a new account.

### Schema version

The payload carries `guest-audit-public/2`. The change from `/1` to `/2` is
**breaking, not additive**: `/1` emitted `scores.geo` and `scores.aeo` separately;
`/2` removes both fields and replaces them with the single rolled-up `scores.aio`.
A consumer still reading `scores.geo` or `scores.aeo` sees them gone, not stale.
`scores.overall` and `scores.seo` are unchanged.

### `aio_insights`

An array of strings describing what the audit found about the target's visibility in
AI answers (AEO and GEO). Order: AEO findings first, then GEO findings, then the
`aeo_improvements` strings. Each finding renders as `"Title. Description"`, or just
`"Title"` when it has no description. Duplicates are removed, keeping the first
occurrence, and the list is **capped at 4 entries**. Raw finding internals beyond
title and description are never emitted.

### Degraded runs

`degradation.fully_measured` is `false` whenever a collector was unavailable, and
`reasons` says which. This matters right now: Firecrawl credits are exhausted, so audits
run on a plain HTTP fetch with no JavaScript rendering and score lower than they should.
Surface this in the UI rather than presenting the score as a clean measurement. Reason
codes: `javascript_not_rendered`, `content_unavailable`, `performance_unavailable`,
`ai_analysis_unavailable`.

## CORS

Readable cross-origin only by the origins in `PUBLIC_SITE_ORIGINS`, without credentials
(`middleware/public_site_cors.py`). Those origins are deliberately absent from
`CORS_ORIGINS`, which is credentialed and applies to every Signal endpoint. Send the
request without cookies (`credentials: "omit"`).

Preprod: the site and Signal are different origins, so `PUBLIC_SITE_ORIGINS` must contain
`https://www.preprod.qiko.ai`. Live: the site is path shared on `https://qiko.ai`, same
origin as the API, so no value is needed.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `RATE_LIMIT_GUEST_AUDIT_PUBLIC` | empty | Per-IP submit limit. Empty reuses `GUEST_AUDIT_LIMIT` / `GUEST_AUDIT_WINDOW_SECONDS`. |
| `GUEST_AUDIT_QUEUE_NAME` | `guest_audit_jobs` | Redis list the audit worker consumes. |
| `GUEST_AUDIT_JOB_TTL_SECONDS` | `1800` | How long a job and its result stay readable. |
| `GUEST_AUDIT_JOB_TIMEOUT_SECONDS` | `300` | Hard ceiling on one run. |
| `GUEST_AUDIT_POLL_INTERVAL_MS` | `3000` | Advertised poll interval. |
| `GUEST_AUDIT_MAX_QUEUE_DEPTH` | `50` | Submissions beyond this are refused with 503. |
| `GUEST_AUDIT_WORKER_CONCURRENCY` | `2` | Guest audits run at once in the audit worker. |
| `GUEST_AUDIT_TARGET_COOLDOWN_SECONDS` | `900` | Repeat submissions for the same target join the running job. |

## Abuse and cost controls

This path is unauthenticated and every submission spends model money. In place:

1. Per-IP submit rate limit, sharing the legacy guest budget by default.
2. Per-target cooldown, so the same target is not paid for twice inside the window.
3. Queue depth ceiling, so a burst is refused rather than queued.
4. Bounded worker concurrency and a per-run timeout.
5. SSRF validation on the target and on every redirect hop
   (`backend/services/url_validation.py`).

**Not** in place: any ceiling on aggregate guest audit spend. Nothing in the repository
caps it today, for either the legacy or the public path. That is a budget decision, not an
implementation detail.

Also note the bot challenge: `/api/guest-audit/challenge` is an HMAC issued and verified
in Signal's **Next.js** BFF (`frontend/src/app/api/guest-audit/`), not in the backend. It
protects Signal's own page only. Any caller reaching FastAPI directly, including the
marketing site, is not challenged. Adding a real challenge (Turnstile is already wired for
the embed widget via `EMBED_CAPTCHA_SECRET_KEY`) is a separate decision.
