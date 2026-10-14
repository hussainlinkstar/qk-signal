# Bing Webmaster reporting contract

Authored for SIGV2-1265, documenting the surface built by SIGV2-1082 and the ingestion path
added by SIGV2-1265. The sibling contracts are `docs/search-console-reporting-contract.md` and
`docs/ga4-reporting-contract.md`.

This file is the source of truth for what every Bing-derived number in Signal means. The
failure mode here is not a crash: it is a number that renders fine and is wrong, or a
connection that looks healthy and has never collected anything.

If a rule here and the code disagree, the code is wrong until this file is deliberately changed.

## 1. Authorization and binding

Bing Webmaster uses **its own OAuth client**, registered as `bing_webmaster` against
`www.bing.com/webmasters/oauth`, with credentials `BING_WEBMASTER_CLIENT_ID` and
`BING_WEBMASTER_CLIENT_SECRET`. It is deliberately separate from the `bing` Microsoft Entra
client used for SSO, whose tokens the Webmaster API does not accept.

The token comes from the OAuth connection bound to the project's `ProjectDataSource` row of
type `bing_webmaster`, resolved project-level first and workspace-level second. The requested
scope is `webmaster.manage`; Bing returns the granted scope as `manage`, and both satisfy the
requirement.

A deployment with no Bing Webmaster credentials is inert rather than broken: connecting is
refused with HTTP 503 naming the missing variables, and reads report
`bing_webmaster_oauth_not_configured`. No token, refresh token, client secret or site
verification code may appear in any response, log line or error detail.

## 2. Ingestion

Ingestion is `app/services/bing_webmaster_service.sync_project_bing_source(db, source)`, and it
is the only path that writes `project_bing_metrics`.

Two callers, one behaviour:

- `backend/monitoring_worker.py` runs it for every active binding on the worker's cadence. This
  is the path that matters: before SIGV2-1265 the only caller was the HTTP handler below, no
  screen called that handler, and a bound Bing site therefore never ingested a single row.
- `GET /api/v1/projects/{project_id}/monitoring/bing-webmaster/metrics` runs it and then reads
  back what was stored.

Order of operations, which is also the security boundary:

1. The binding must carry a site URL. A binding without one is `provider_error` with
   `missing_site_url` and is not sent to Bing.
2. `GetUserSites` is called first. **A site the connected account does not own is refused
   before any stats call**, as `site_not_owned`. Ownership is the account's own list, never a
   string the customer typed.
3. `GetRankAndTrafficStats`, `GetQueryStats` and `GetPageStats` are fetched for Bing's fixed
   recent window. Bing does not accept an arbitrary range, so none is offered.
4. Rows are upserted on the grain below. Re-running is idempotent: it updates in place and
   never duplicates or double-counts.

## 3. Grain and storage

`project_bing_metrics`, unique on `(project_id, site_url, dimension_type, dimension, date)`.

| `dimension_type` | `dimension` | Source call |
|---|---|---|
| `site` | `""` | `GetRankAndTrafficStats` |
| `query` | the query text | `GetQueryStats` |
| `page` | the page URL | `GetPageStats` |

Dates arrive as .NET `/Date(<epoch_ms><±HHMM>)/`. The calendar day is taken in the offset Bing
declared and stored as a plain UTC date, so the day Bing meant is the day stored. A row that
cannot be dated is dropped rather than guessed at.

**Query and page rows are breakdowns of the same traffic.** Site-level rows are the only
honest total. Nothing may sum the three dimensions together, and no consumer may derive a site
total from the query or page breakdown.

## 4. Position is unavailable, and that is a decision

Bing's reference types `AvgClickPosition` and `AvgImpressionPosition` as `int` and never
documents the scale. The raw integers are persisted verbatim as `avg_click_position_raw` and
`avg_impression_position_raw`, and **every** payload reports position as:

```json
{ "status": "unavailable", "reason": "bing_position_scale_unverified" }
```

No surface, audit sentence, report or export may render a Bing position, scale one, or compare
one to a Search Console position. Publishing a plausible guess is worse than publishing a gap,
because a gap gets asked about and a wrong number does not. Changing this needs documented
evidence of the scale from Microsoft, not an inference from observed values.

## 5. Bing is never Search Console

`project_bing_metrics` and `project_gsc_page_metrics` are separate datasets with separate
tables, separate aggregates and separate sentences. They are never merged, averaged together,
summed into a combined total, or presented as each other. The two providers measure different
indexes with different methodologies, and a blended number would be meaningless in both.

## 6. Response states

`GET /api/v1/projects/{project_id}/monitoring/bing-webmaster/metrics`

| Condition | `status` | `availability` | `reason` | `last_status` |
|---|---|---|---|---|
| No active binding for the project | `disconnected` | `disconnected` | - | untouched |
| Binding has no site URL | `provider_error` | `unavailable` | `missing_site_url` | `error` |
| Deployment has no Bing credentials | `unavailable` | `unavailable` | `bing_webmaster_oauth_not_configured` | untouched |
| No usable grant, or refresh failed | `revoked` | `unavailable` | - | `auth_error` |
| Site not in the connected account | `site_not_owned` | `unavailable` | `site_not_in_account` | `auth_error` |
| Bing refused or failed the call | `provider_error` | `unavailable` | provider reason code | `error` |
| Ingested, rows present | `ok` | `ok` | - | `fresh` |
| Ingested, provider returned nothing | `ok` | `ok` | - | `connected_no_data` |

An unconfigured deployment leaves `last_status` alone on purpose: that is a deployment fact,
not something wrong with the customer's binding.

A success payload carries `provider: "bing_webmaster"`, the `site_url`, the `period` the stored
rows **actually** cover (never the period that was asked for), the unavailable `position` block
from section 4, and the `site`, `queries` and `pages` row lists.

## 7. Use in audits

`services/audit_search_metrics.py` reads the stored rows for the last 28 days and hands the
audit an aggregate as T1 evidence: clicks and impressions from site rows only, the covered
period, the number of distinct queries and pages, and the top queries.

- A provider with no binding reports `no_active_binding`. A binding with no stored rows reports
  `no_stored_rows`. **Neither is reported as zero traffic**, and the audit says the traffic is
  unknown rather than absent.
- Section 4 applies in full: no audit sentence may state a Bing position.
- The audit reads storage only. It never calls Bing, so an upstream outage can delay data but
  can never slow down or fail an audit.
