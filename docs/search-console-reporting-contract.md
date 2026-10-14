# Search Console reporting contract

Authored for SIGV2-1025. Companion to `ga4-reporting-contract.md`, and it depends on it: the
Sessions column in the SEO Pages table comes from GA4, never from Search Console.

Same reason for existing as the GA4 contract. Nothing here crashes when it is wrong. It renders
a number that a customer will act on.

Every rule below is checked against the Search Console API documentation as of 2026-09-30, not
assumed. Where a rule follows from a documented API behaviour, the behaviour is stated so a
reviewer can confirm it without re-reading Google's docs.

## 1. Authorization and binding

Performance data is read with the customer's OAuth connection bound to the project's
`ProjectDataSource` row of type `GOOGLE_SEARCH_CONSOLE`, resolved project-level first and
workspace-level second, exactly as GA4 does. There is no second credential store and no
service account. Token refresh goes through the one shared Google refresh primitive.

The bound `source_id` is the Search Console property. Two forms exist and both must work:

- **URL-prefix**: `https://www.example.com/`, which is **URL-encoded into the request path**
  (`.../sites/https%3A%2F%2Fwww.example.com%2F/searchAnalytics/query`).
- **Domain**: `sc-domain:example.com`, encoded the same way.

The property is confirmed to belong to the requesting tenant before any fetch. Tokens, refresh
tokens and client secrets never appear in a response, a log line or an error detail.

## 2. Metric definitions

Endpoint: `POST https://www.googleapis.com/webmasters/v3/sites/{encodedSiteUrl}/searchAnalytics/query`.

| Metric | Aggregating across rows |
|---|---|
| `clicks` | **Additive.** Sum. |
| `impressions` | **Additive.** Sum. |
| `ctr` | **Never averaged.** Recompute: `SUM(clicks) / SUM(impressions)`. |
| `position` | **Never averaged.** Impression-weighted: `SUM(position_row * impressions_row) / SUM(impressions_row)`. |

`position` as returned by the API is already an average for that row. Taking a mean of means
across pages or days is wrong whenever impressions differ between rows, which is always. This
is the specific error the ticket calls out, so it gets a test with a deliberately lopsided
fixture where a plain mean and the weighted value differ visibly.

Zero total impressions yields `null` for both `ctr` and `position`, never `0`. A position of
`0` is not a real value and must never be rendered.

## 3. Dates, freshness and completeness

**Search Console reports in Pacific Time.** The API documents `startDate` and `endDate` as
"in PT time (UTC - 7:00/8:00)", and the response `metadata` object states that all its dates
and times are in `America/Los_Angeles`.

**GA4 reports in the property's own timezone.** These two do not align, and pretending they do
is the trap in this ticket.

The rule: **do not silently align them.** A Search Console day is labelled as a Search Console
day, and every payload states `date_basis: "America/Los_Angeles"` for GSC-sourced series
alongside the GA4 property timezone for GA4-sourced values. When the two differ, the payload
carries an explicit `date_alignment: "approximate"` flag and names both zones. Only when the
GA4 property timezone is itself `America/Los_Angeles` may alignment be reported as `exact`.

Fabricating a conversion between them would be worse than disclosing the mismatch: a PT day
maps onto parts of two days in any other zone, so no exact per-day mapping exists.

### 3.1 Incomplete data is not missing data

Request `dataState: "all"` and read the returned `metadata`:

- `first_incomplete_date` marks where data is still being collected. Rows on and after it are
  flagged `incomplete` and must not be presented as settled numbers.
- Requesting `dataState: "full"` instead returns only finalized data. Either is acceptable, but
  the choice is recorded in the payload so a consumer knows which it received.

### 3.2 A missing day is not a zero

The API omits days with no data entirely rather than returning zero rows. A gap in the returned
series therefore means "no data returned", which is not the same as "no impressions". Gaps are
rendered as unavailable, never backfilled with zeros.

## 4. Pagination and the hard ceiling

- `rowLimit` is valid from 1 to **25,000**, default 1,000. Always set it explicitly.
- Page by incrementing `startRow` by the row limit until a response returns zero rows. A
  response with fewer rows than requested is also the last page.
- **There is a hard ceiling of 50,000 rows per day per search type**, and the documentation
  states plainly that the API "does not guarantee to return all data rows but rather top ones",
  sorted by clicks descending.

So a full enumeration is not available in general. Any result that hit the ceiling, or that
stopped at the configured page bound, is returned with `completeness: "partial"` and the reason.
Never present a truncated top-N as a total.

### 4.1 Query-level totals do not reconcile to site totals

Search Console withholds anonymised queries. Summing the query dimension therefore produces
less than the property total, by design. Query-level figures are never presented as summing to
the site total, and no residual is invented to make them.

## 5. Aggregation type

`aggregationType` is `auto`, `byPage` or `byProperty`. Grouping or filtering by `page` forbids
`byProperty`; use `auto` there. The response echoes `responseAggregationType`, and that echoed
value is recorded in the payload rather than the requested one, because the two can differ.

## 6. The Pages table

Columns are Page, Sessions, Avg. position, Opportunity.

- **Page, Avg. position** come from Search Console, aggregated per section 2.
- **Sessions comes from GA4**, per `ga4-reporting-contract.md`. Search Console clicks are not
  sessions and must never be relabelled as them. If no authorized GA4 binding exists for the
  project, Sessions is reported as unavailable with a reason. It is not filled with clicks.

### 6.1 URL normalization for the GA4 join

Search Console returns a full canonical URL; GA4 returns a path. Normalize both to a comparison
key:

1. Strip scheme and host.
2. Strip query string and fragment.
3. Percent-decode, then lowercase the host-free path.
4. Preserve a trailing slash except on the root path, which normalizes to `/`.

Where several Search Console URLs collapse to one key, their metrics are combined using the
section 2 rules and the collapse count is returned as evidence. The normalization actually
applied is named in the payload, so a mismatched row can be diagnosed instead of guessed at.

A GSC page with no GA4 counterpart reports Sessions as unavailable, not zero. The reverse also
holds.

## 7. Opportunity

**Opportunity is a classification with its evidence attached, not a score.** The ticket forbids
a hardcoded opportunity score or a fabricated ranking, and any invented CTR curve would be
exactly that, so none is used. The baseline is the property's own data.

| Value | Rule |
|---|---|
| `striking_distance` | Weighted position is between 4 and 20 inclusive, and impressions meet the configured minimum. The page already ranks but sits below the fold. |
| `low_ctr` | Weighted position is 3 or better, and CTR is below the median CTR of this property's own pages in the same position band. |
| `none` | Neither rule matches and impressions meet the minimum. |
| `insufficient_data` | Impressions are below the configured minimum, or the row is flagged incomplete. |

Every row returns the inputs that produced its classification: weighted position, impressions,
CTR, the band median where one was used, and the minimum-impressions threshold in force. A
consumer can therefore re-derive the verdict. The thresholds are configuration, not literals
scattered through the code.

`insufficient_data` is distinct from `none`. One means we did not look hard enough, the other
means we looked and there is nothing there.

## 8. Storage

Additive schema only, at the grain this feature needs: property, page, date, clicks,
impressions, position, plus the completeness flag. Query-level rows are stored only if a
consumer needs them, at the same grain plus query.

**Do not restore `project_gsc_snapshots`.** It was shaped for the ROI Simulator, de-scoped in
`ef197db9`, and dropped deliberately. Its shape does not fit the Pages tab or the Settings
connect state.

Re-running ingestion for a period that already has data updates in place. It does not duplicate
rows and does not double count. Backfills are queued and bounded.

## 9. Connection states

Seven states, distinguishable, landing on `last_sync_at` / `last_status` / `last_error`:
`disconnected`, `connected_no_data`, `syncing`, `fresh`, `stale`, `revoked`, `provider_error`.

A catalog selection is not successful ingestion. A property chosen in Settings with no
completed sync is `connected_no_data`, never `fresh`.

HTTP 403 means revoked or insufficient permission on that property and maps to `revoked`.
HTTP 429 is rate limiting and maps to `provider_error` with a retry indication, not to
`revoked`. The two must not be collapsed, because one needs the customer to reconnect and the
other needs us to wait.
