# GA4 reporting contract

Authored for SIGV2-1001, which absorbs SIGV2-1002 (channel mix) and SIGV2-1003 (conversions).

This file is the source of truth for what every GA4-derived number in Signal means. It exists
because the failure mode here is not a crash: it is a number that looks reasonable, renders
fine, and is wrong. Summing a de-duplicated user count, averaging an average, or letting AI
referrals be counted twice all produce plausible output. Every rule below is written so a
reviewer can check the implementation against it without re-deriving GA4 semantics.

If a rule here and the code disagree, the code is wrong until this file is deliberately changed.

## 1. Authorization and binding

Site-wide traffic is read with **the customer's own OAuth token**, never a shared service
account. The token comes from the OAuth connection bound to the project's
`ProjectDataSource` row of type `GOOGLE_ANALYTICS_4`, resolved project-level first and
workspace-level second. Scope is `analytics.readonly`. Expired tokens are refreshed against
Google's token endpoint and the rotated token is persisted.

A property is read only after confirming the binding belongs to the requesting tenant. No
token, refresh token or client secret may appear in any response, log line or error detail.

The pre-existing service-account path in `ga4_traffic_service.py` stays only for the
AI-referral snapshot job it already serves. It must not be used for anything in this contract.

## 2. Metric definitions

| KPI | GA4 source | Aggregating across days or rows |
|---|---|---|
| Sessions | `sessions` | **Additive.** Sum. |
| Pageviews | `screenPageViews` | **Additive.** Sum. |
| Key events | `keyEvents` | **Additive.** Sum. |
| Engaged sessions | `engagedSessions` | **Additive.** Sum. |
| Users | `totalUsers` | **Not additive. Never sum.** See 2.1. |
| Engagement rate | derived | `SUM(engagedSessions) / SUM(sessions)`. See 2.2. |
| Bounce rate | derived | `1 - engagementRate`. Never summed or averaged directly. |
| Avg session duration | `averageSessionDuration` | Session-weighted. See 2.3. |

### 2.1 totalUsers is de-duplicated and must not be summed

GA4 de-duplicates users *within the requested date range*. A user who visits on three days
counts once for a 7-day range but appears in three daily rows. Summing daily rows inflates the
number, and inflates it more the longer the period.

**Rule:** request `totalUsers` with the reporting period as a **single `dateRange`**. Never
derive a period user count by summing daily or per-source rows. The same applies across the
channel dimension: users cannot be summed across channel groups either, because one user can
arrive through two channels.

The current-period and previous-period user counts may be fetched in one request using two
`dateRanges` entries, which is the preferred shape.

A consequence to accept rather than work around: per-channel user counts do not add up to the
site total, and must never be presented as if they do. If a channel-level user count is shown
at all, it is labelled as such and no total row is derived from it.

### 2.2 Rates are computed from components, not averaged

Do not request `engagementRate` or `bounceRate` and average the returned values, and do not
weight them either. Request the **component counts** and divide the sums:

```
engagementRate = SUM(engagedSessions) / SUM(sessions)
bounceRate     = 1 - engagementRate
```

This is exact. Averaging per-row rates is wrong whenever rows have unequal session counts,
which is always.

If `SUM(sessions)` is zero the rate is `null` and is reported as unavailable, not as `0`.

### 2.3 Average session duration is session-weighted

GA4 exposes no total-duration metric, so the per-row average must be re-weighted:

```
avgSessionDuration = SUM(averageSessionDuration_row * sessions_row) / SUM(sessions_row)
```

Zero total sessions yields `null`, not `0`.

### 2.4 Audience is not defined and must not be invented

The Overview mockup shows an "Audience" KPI with no definition behind it. Do not implement it
as a relabelled `totalUsers`, and do not invent a meaning. Return it as unavailable and raise
the definition question. Shipping a plausible guess here is worse than shipping a gap, because
a gap gets asked about and a wrong number does not.

## 3. Periods and comparison

Supported windows: **7D, 15D, 90D, 12M**, each with its immediately preceding interval of equal
length as the comparison period.

- Boundaries are computed in the **GA4 property's timezone**, not the server's and not the
  user's. The property timezone is read from the Admin API and persisted on the binding; it is
  returned in every payload alongside the boundaries.
- Every response states: start date, end date, comparison start, comparison end, property
  timezone, data freshness timestamp, and an availability status.
- Bucket granularity: daily for 7D and 15D, weekly for 90D, monthly for 12M. The bucket
  boundary rule is stated in the payload so a consumer never has to guess.
- Ranges are validated and bounded. A request outside the supported set is rejected, not
  silently clamped.

### 3.1 Change semantics

- **Volume metrics** (sessions, pageviews, key events) report a **relative change**:
  `(current - previous) / previous`.
- **Share metrics** (channel mix percentages) report a **percentage-point change**:
  `current_share - previous_share`. Never a relative change of a percentage.
- Every change value is labelled with which of the two it is. The two are routinely confused
  and the confusion is invisible in the rendered output.
- If `previous` is zero, missing, or the previous period is not covered by available data, the
  change is `null` and reported as unavailable. Never infinity, never 100%, never "new".

## 4. Channel mix

Dimension: `sessionDefaultChannelGroup`.

Six presentation buckets are required: **Organic, Direct, Referral, AI, Paid, Social**, plus a
mandatory seventh, **Other**.

### 4.1 Mapping, mutually exclusive

| Bucket | GA4 channel groups |
|---|---|
| Organic | Organic Search |
| Direct | Direct |
| Paid | Paid Search, Paid Shopping, Paid Video, Display, Cross-network, Paid Social |
| Social | Organic Social |
| Referral | Referral |
| Other | everything else: Email, Affiliates, Organic Video, Organic Shopping, Audio, SMS, Mobile Push Notifications, Unassigned, and any group GA4 adds later |

The mapping lives in exactly one table in the code. An unrecognised channel group falls into
**Other**, never into a guessed bucket and never dropped.

**Paid Social is assigned to Paid, not Social.** This is a judgement call, recorded as one:
the Paid bucket answers "what did spend produce", and Social then means organic social, which
keeps it comparable with Organic. Flagged to Jake for confirmation; changing it is a one-line
change to the table above and to the code table that mirrors it.

### 4.2 AI must be subtracted from its host channel, not added alongside

GA4 has no AI channel. AI assistants land in whichever group GA4 assigns them, usually Referral
but **not always**: `search.brave.com` is in the AI source list and GA4 classifies it as Organic
Search.

So the AI bucket cannot be built by filtering Referral. It is built by:

1. Requesting `sessionSource` alongside `sessionDefaultChannelGroup`.
2. Rows whose `sessionSource` is in `LLM_REFERRAL_SOURCES`
   (`app/services/geo/ga4_traffic_service.py`) are attributed to **AI**.
3. Those same sessions are **subtracted from whichever bucket their channel group mapped to**.

Double-counting here is the single most likely defect in this ticket and the hardest to notice,
because the six buckets still look sensible. It gets a test with hand-calculated expected
values, including at least one AI source that is not Referral.

### 4.3 Shares reconcile, and nothing is discarded to make them

- The denominator is **all-traffic sessions for the period**, including Other.
- Shares are computed to one decimal place and are **not** normalised to sum to 100. Rounding
  residue is left visible rather than absorbed.
- Organic + Direct + Referral + AI + Paid + Social + Other must reconcile to the total within
  rounding. A test asserts this on a fixture whose Other bucket is non-empty.
- Never drop residual traffic to force six buckets to 100%.
- With zero sessions in the period, shares are `null` and reported unavailable, not zero.

## 5. Key events (conversions)

Metric `keyEvents`, with `eventName` for the per-event breakdown and
`sessionDefaultChannelGroup` for the per-channel breakdown. Site total and per-channel totals
use the same intervals as everything else. A key event is attributed once; no breakdown may
double-count against the total.

### 5.1 Zero is not the same as unconfigured

A zero `keyEvents` result does not prove the property has no key events configured. Three
distinct states, and the payload must distinguish them:

| State | Condition |
|---|---|
| `observed_zero` | The Admin API lists one or more key events, and the report returns zero for the period. |
| `not_configured` | The Admin API call succeeded and returned an empty key-event list. This is the only case that may claim not-configured. |
| `unknown` | The Admin API call failed, was unauthorized, or was not attempted. |

Returning `not_configured` without a successful Admin API listing is a contract violation.

## 6. Data quality and integrity

- **Cardinality limits.** GA4 collapses high-cardinality results into an `(other)` row and
  flags the response. Detect that flag, surface the result as partial, and never present a
  collapsed row as a real channel or event. Confirm the exact response field against the
  current Data API schema rather than assuming a name.
- **Sampling and thresholding.** If GA4 reports the response as sampled or thresholded, the
  payload says so. A thresholded zero is not a measured zero.
- **Pagination.** Requests that can exceed the row limit paginate to completion, with a bounded
  maximum. A truncated result is reported as partial, never as complete.
- **Idempotent sync.** Re-running ingestion for a period that already has data updates in place
  and does not duplicate rows or double-count. Backfills are queued and bounded; ingestion is
  never triggered per keystroke or per page view.
- **Distinct states.** Measured zero, disconnected, no data yet, syncing, stale,
  provider error, revoked and permission denied are eight different things and are reported as
  eight different things. They land on the `last_sync_at` / `last_status` / `last_error` columns.
- **Compatibility.** The existing `LLMTrafficSnapshot` reads and the `/llm-traffic` contract
  keep working unchanged.

### 6.1 Authorization failures (SIGV2-1202)

A 401 and a 403 from Google are different facts and the payload never collapses them.

| Condition | Status | `reason` | `last_status` | What fixes it |
|---|---|---|---|---|
| No OAuth grant on the binding | `disconnected` | - | `disconnected` | Connect an account, bind a property |
| Grant exists, token invalid or unrefreshable, or GA4 answered 401 | `revoked` | - | `auth_error` | Reconnect the same account |
| GA4 answered 403, property not shared with this account | `permission_denied` | `property_denied` | `permission_denied` | Choose a property this account can read, or connect the owning account |
| GA4 answered 403, grant missing the Analytics scope | `permission_denied` | `insufficient_scope` | `permission_denied` | Reconnect and grant Analytics read access |
| GA4 answered 403, not classifiable | `permission_denied` | `permission_denied` | `permission_denied` | Stated as a denial without claiming which |

Rules this encodes, each because the opposite was shipped and produced a reconnect loop:

- A 403 is **never** reported as `revoked`. The authorization is valid; the account is refused.
  Telling the customer to reconnect sends them round a loop that cannot end, because
  reconnecting the same account does not change what it may read.
- A missing grant is `disconnected`, not `revoked`. A disconnect nulls the binding's FK
  (ON DELETE SET NULL), so "revoked" accused the customer of losing access one click after
  they gave it up themselves.
- `reason` comes from a fixed vocabulary (`GA4_REASON_*`). Google's error text can name the
  signed-in account, so provider text is used for classification only and never propagated.
- `property_denied` is asserted only on positive evidence in the provider's error. An
  unrecognised 403 reports `permission_denied` and claims nothing more.

### 6.2 Binding lifecycle against a changing grant (SIGV2-1202)

A workspace grant and a saved property are separate facts, and the property is only ever valid
for the account that granted it.

- Disconnecting a workspace grant clears the bindings that depended on it in the same
  transaction: property id, label, connection FK, live binding metadata and stale errors go,
  and the binding is marked inactive and `disconnected`. Scoped to that workspace and that
  provider. Client magic-link bindings, project-level grants, other workspaces and other
  providers are untouched. History (traffic rows, audits, reports, audit logs) is never deleted.
- Reconnecting validates every saved workspace binding against the new token before reusing it.
  A property the new grant can read keeps its binding and has stale errors cleared; a property
  it is confirmed to be refused loses its binding and requires a fresh selection; a property
  the customer had already cleared stays unbound.
- **An uncertain signal never erases a binding.** A 429, an outage, a network failure, a token
  problem, a partial catalogue, an unparseable id or a cancelled OAuth all mean "unknown", and
  unknown keeps the binding and defers. Only an unambiguous refusal of the object itself
  (403 or 404 on that property or site) may clear one.
- Search Console access is validated against its own object. GA4 access proves nothing about
  site ownership, and the reverse.

## 7. Open questions, not to be resolved by guessing

1. **Audience.** Undefined in the mockup. Blocked pending a definition; see 2.4.
2. **Paid Social.** Assigned to Paid by the judgement recorded in 4.1. Needs Jake's
   confirmation, not because it is hard to change, but because it changes a number a customer
   will read.
