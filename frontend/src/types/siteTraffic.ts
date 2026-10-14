// SIGV2-1035: frontend types for GET /api/v1/projects/{id}/monitoring/site-traffic.
// Field names mirror docs/ga4-reporting-contract.md and
// backend/app/services/geo/ga4_reporting_service.py one-to-one so a reviewer
// can diff this file against the payload builder without translation.

export type SiteTrafficWindow = "7D" | "15D" | "90D" | "12M";

export const SITE_TRAFFIC_WINDOWS: SiteTrafficWindow[] = ["7D", "15D", "90D", "12M"];

export type SiteTrafficAvailability =
  | "available"
  | "partial"
  | "no_data"
  | "unavailable"
  | "disconnected";

export type SiteTrafficKeyEventState = "active" | "observed_zero" | "not_configured" | "unknown";

// Contract 3.1: volume changes are relative ratios; share changes are
// percentage points. The kind is carried on every value so the two are never
// confused in the rendered output.
export type ChangeKind = "relative" | "percentage_points";

export interface SiteTrafficChange {
  value: number | null;
  kind: ChangeKind;
}

export interface SiteTrafficOverview {
  sessions: number;
  pageviews: number;
  key_events: number;
  engaged_sessions: number;
  // Contract 2.1: de-duplicated, from a single-range request; null when absent.
  total_users: number | null;
  // Contract 2.2/2.3: derived server-side; null when the denominator is zero.
  engagement_rate: number | null;
  bounce_rate: number | null;
  avg_session_duration: number | null;
  // Contract 2.4: never a number. The metric has no agreed definition yet.
  audience: { value: null; available: false; reason: string };
  changes: {
    sessions: SiteTrafficChange;
    pageviews: SiteTrafficChange;
    key_events: SiteTrafficChange;
    total_users: SiteTrafficChange;
  };
}

export interface SiteTrafficSeriesPoint {
  bucket: string;
  sessions: number;
  pageviews: number;
  key_events: number;
}

export interface SiteTrafficChannelBucket {
  bucket: string;
  label: string;
  sessions: number;
  share: number | null;
  share_change: SiteTrafficChange;
}

export interface SiteTrafficKeyEvents {
  state: SiteTrafficKeyEventState;
  total: number;
  change: SiteTrafficChange;
  by_event: { event_name: string; key_events: number }[];
  by_channel: { bucket: string; label: string; key_events: number }[];
}

// Per-KPI hover-panel factor rows. `bucket`-keyed rows cover the channel
// breakdowns (sessions/users/conversions); `metric`-keyed rows cover the
// engagement components. Per contract 2.1 the users rows are GA4 per-channel
// counts that overlap - change factors only, never summed to a total.
export interface SiteTrafficBreakdownRow {
  bucket?: string;
  metric?: string;
  label?: string;
  change: SiteTrafficChange;
  // The current period on its own. A change needs two periods and a new GA4
  // property only has one, so without this a change-only row had nothing to
  // render and was dropped, taking every row on every card with it.
  // `value_kind` says how to format it; absent means a plain count.
  value?: number | null;
  value_kind?: "count" | "percent" | "seconds";
}

export interface SiteTrafficBreakdowns {
  sessions: SiteTrafficBreakdownRow[];
  users: SiteTrafficBreakdownRow[];
  engagement: SiteTrafficBreakdownRow[];
  conversions: SiteTrafficBreakdownRow[];
}

export interface SiteTrafficDataQuality {
  data_loss_from_other_row?: boolean;
  subject_to_thresholding?: boolean;
  truncated?: boolean;
  timezone_source?: string;
  [key: string]: unknown;
}

export interface SiteTrafficPayload {
  status: "ok";
  window: SiteTrafficWindow;
  start_date: string;
  end_date: string;
  comparison_start_date: string;
  comparison_end_date: string;
  property_timezone: string;
  bucket_granularity: "daily" | "weekly" | "monthly" | string;
  bucket_boundary: string;
  data_freshness: string;
  availability: SiteTrafficAvailability;
  data_quality: SiteTrafficDataQuality;
  overview: SiteTrafficOverview;
  series: SiteTrafficSeriesPoint[];
  channel_mix: SiteTrafficChannelBucket[];
  // Optional: payloads written before this field existed, and the
  // visual-suite stub, have no `breakdowns`. Typing it as required let a
  // bare index compile, and that index threw at runtime and removed the
  // whole section instead of one hover panel.
  breakdowns?: SiteTrafficBreakdowns;
  key_events: SiteTrafficKeyEvents;
}

// The router returns these shapes instead of a payload when the read cannot
// run (contract 6: disconnected, revoked and provider_error are distinct).
//
// SIGV2-1202: permission_denied is the fourth. It means the Google
// authorization is valid and Google refused the request anyway - the property
// is not shared with this account, or the grant lacks the Analytics scope.
// Reporting that as "revoked" sent customers to reconnect an account that was
// never broken, which is the reconnect loop this status exists to end.
export type SiteTrafficUnavailableStatus =
  | "disconnected"
  | "revoked"
  | "permission_denied"
  | "provider_error";

// Fixed vocabulary from the backend (GA4_REASON_* in
// backend/app/services/geo/ga4_reporting_service.py). It never carries
// provider text, so it cannot leak an account identifier into the UI.
export type SiteTrafficPermissionReason =
  | "property_denied"
  | "insufficient_scope"
  | "permission_denied";

export interface SiteTrafficUnavailable {
  status: SiteTrafficUnavailableStatus;
  availability: string;
  /** Present on permission_denied only. */
  reason?: SiteTrafficPermissionReason | string;
}

export type SiteTrafficResponse = SiteTrafficPayload | SiteTrafficUnavailable;
