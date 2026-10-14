import { requestJson } from "@/services/http";

export type RecommendationDecisionType = "accepted" | "dismissed";

export type RecommendationDecision = {
  id: number;
  project_id: number;
  /**
   * Either `problem:<code>` (deterministic identity) or the legacy sha256
   * digest of the action text. Both forms stay valid; reads accept either.
   */
  action_fingerprint: string;
  /** Human-readable summary of the Advisor action; null for legacy rows. */
  action_label?: string | null;
  decision: RecommendationDecisionType;
  note: string | null;
  decided_by: number | null;
  created_at: string | null;
};

export type RecommendationDecisionPayload = {
  /** Raw advisor action text; the backend derives a sha256 fingerprint from it. */
  action_text: string;
  /**
   * The action's deterministic problem code when it has one. Sending it keys
   * the decision on the failing check rather than on the action text, which an
   * LLM rewrites on every audit, so the dismissal survives (SIGV2-1118).
   */
  problem_code?: string | null;
  decision: RecommendationDecisionType;
  note?: string;
};

const recommendationDecisionsEndpoint = (projectId: string | number): string =>
  `/api/projects/${projectId}/recommendation-decisions`;

export async function fetchRecommendationDecisions(
  projectId: string | number,
  headers: HeadersInit = {}
): Promise<RecommendationDecision[]> {
  return requestJson<RecommendationDecision[]>({
    endpoint: recommendationDecisionsEndpoint(projectId),
    method: "GET",
    headers,
    errorMessage: "Unable to load recommendation learnings.",
  });
}

export async function recordRecommendationDecision(
  projectId: string | number,
  payload: RecommendationDecisionPayload,
  headers: HeadersInit = {}
): Promise<RecommendationDecision> {
  return requestJson<RecommendationDecision>({
    endpoint: recommendationDecisionsEndpoint(projectId),
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to record recommendation decision.",
  });
}
