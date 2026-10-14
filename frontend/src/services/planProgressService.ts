import { requestJson } from "@/services/http";

/**
 * Read-only Advisor "plan progress" over time for an Executive project (R12).
 *
 * Mirrors the backend `AdvisorPlanProgressResponse` shape exposed at
 * `GET /api/v1/projects/{project_id}/advisor-plan-progress`, proxied through the
 * frontend at `/api/projects/{projectId}/advisor-plan-progress`. The endpoint is
 * gated on `has_done_for_you_execution` (Executive+) and returns 402 when the
 * plan lacks the capability — surfaced here as an `HttpRequestError` with
 * `status === 402` so callers can render the upsell.
 */

/** Per-snapshot count rollup of the deterministic Advisor plan. */
export type PlanSummary = {
  total_actions: number;
  high_impact: number;
  medium_impact: number;
  low_impact: number;
};

/** One point on the trend line — counts for a single audit snapshot. */
export type PlanTrendPoint = {
  /** ISO timestamp of the snapshot; null for legacy rows. */
  created_at: string | null;
  total_actions: number;
  high_impact: number;
};

/** A single Advisor action, normalised to a stable fingerprint. */
export type PlanActionDelta = {
  fingerprint: string;
  action: string;
  title: string | null;
  impact: string | null;
  effort: string | null;
  rank: number | null;
};

/** Difference between the two most recent snapshots. */
export type PlanDelta = {
  actions_added: PlanActionDelta[];
  actions_resolved: PlanActionDelta[];
  actions_carried: PlanActionDelta[];
  /** curr-minus-prev per summary count key (can be negative). */
  impact_delta: PlanSummary;
  summary_prev: PlanSummary | null;
  summary_curr: PlanSummary | null;
};

/** Full progress payload. Degrades to an empty-but-valid shape with few snapshots. */
export type PlanProgress = {
  latest_summary: PlanSummary | null;
  first_summary: PlanSummary | null;
  trend: PlanTrendPoint[];
  /** null when fewer than two snapshots exist. */
  latest_delta: PlanDelta | null;
};

const advisorPlanProgressEndpoint = (projectId: string | number): string =>
  `/api/projects/${projectId}/advisor-plan-progress`;

export async function fetchAdvisorPlanProgress(
  projectId: string | number,
  headers: HeadersInit = {}
): Promise<PlanProgress> {
  return requestJson<PlanProgress>({
    endpoint: advisorPlanProgressEndpoint(projectId),
    method: "GET",
    headers,
    errorMessage: "Unable to load Advisor plan progress.",
  });
}
