import { requestJson, requestVoid } from "@/services/http";
import type { SiteTrafficResponse, SiteTrafficWindow } from "@/types/siteTraffic";
import type {
  CreateTargetKeywordPayload,
  CreateVisibilityQueryPayload,
  GenerateBasePromptsResponse,
  SearchConsolePagesResponse,
  SerpTrackingSummary,
  TargetKeyword,
  OffPageMentionFeedItem,
  OffPageMentionTrendResponse,
  OffPageMentionsSummaryResponse,
  PublicVolatilityDashboardResponse,
  VolatilitySummaryResponse,
  VolatilityTrendResponse,
  UpdateVisibilityQueryPayload,
  VisibilityQuery,
  VisibilityQueryListResponse,
  VisibilitySummaryResponse,
  VisibilityTrendResponse,
} from "@/types/monitoring";

type AuthHeaders = HeadersInit;

export async function fetchVisibilityQueries(
  projectId: number | string,
  headers: AuthHeaders,
  includeInactive = true
): Promise<VisibilityQueryListResponse> {
  return requestJson<VisibilityQueryListResponse>({
    endpoint: `/api/v1/projects/${projectId}/monitoring/visibility-queries?include_inactive=${includeInactive ? "true" : "false"}`,
    method: "GET",
    headers,
    errorMessage: "Failed to load visibility queries.",
  });
}

export async function createVisibilityQuery(
  projectId: number | string,
  payload: CreateVisibilityQueryPayload,
  headers: AuthHeaders
): Promise<VisibilityQuery> {
  return requestJson<VisibilityQuery>({
    endpoint: `/api/v1/projects/${projectId}/monitoring/visibility-queries`,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Failed to create visibility query.",
  });
}

export async function updateVisibilityQuery(
  projectId: number | string,
  queryId: number,
  payload: UpdateVisibilityQueryPayload,
  headers: AuthHeaders
): Promise<VisibilityQuery> {
  return requestJson<VisibilityQuery>({
    endpoint: `/api/v1/projects/${projectId}/monitoring/visibility-queries/${queryId}`,
    method: "PATCH",
    headers,
    body: payload,
    errorMessage: "Failed to update visibility query.",
  });
}

/**
 * Ask Signal to fill the project's uncovered search types with generated base
 * prompts (SIGV2-1186). Idempotent and plan-bounded on the backend, so calling
 * it twice adds nothing; `reason` says why `created` is empty when it is.
 */
export async function generateBaseVisibilityPrompts(
  projectId: number | string,
  headers: AuthHeaders
): Promise<GenerateBasePromptsResponse> {
  return requestJson<GenerateBasePromptsResponse>({
    endpoint: `/api/v1/projects/${projectId}/monitoring/visibility-queries/generate-base`,
    method: "POST",
    headers,
    errorMessage: "Failed to generate base prompts.",
  });
}

export async function deleteVisibilityQuery(
  projectId: number | string,
  queryId: number,
  headers: AuthHeaders
): Promise<void> {
  return requestVoid({
    endpoint: `/api/v1/projects/${projectId}/monitoring/visibility-queries/${queryId}`,
    method: "DELETE",
    headers,
    errorMessage: "Failed to delete visibility query.",
  });
}

export async function fetchVisibilitySummary(
  projectId: number | string,
  headers: AuthHeaders
): Promise<VisibilitySummaryResponse> {
  return requestJson<VisibilitySummaryResponse>({
    endpoint: `/api/v1/projects/${projectId}/monitoring/visibility-summary`,
    method: "GET",
    headers,
    errorMessage: "Failed to load AI visibility summary.",
  });
}

export async function fetchVisibilityTrends(
  projectId: number | string,
  headers: AuthHeaders,
  days = 30
): Promise<VisibilityTrendResponse> {
  return requestJson<VisibilityTrendResponse>({
    endpoint: `/api/v1/projects/${projectId}/monitoring/visibility-trends?days=${days}`,
    method: "GET",
    headers,
    errorMessage: "Failed to load AI visibility trends.",
  });
}

// SIGV2-1036: SERP keyword tracking + Search Console pages feeds for the SEO
// detail tabs. Both return exactly what the backend emits; the search-console
// response is the union documented in docs/search-console-reporting-contract.md.
export async function fetchSerpTrackingSummary(
  projectId: number | string,
  headers: AuthHeaders
): Promise<SerpTrackingSummary> {
  return requestJson<SerpTrackingSummary>({
    endpoint: `/api/v1/projects/${projectId}/monitoring/serp-tracking`,
    method: "GET",
    headers,
    errorMessage: "Failed to load keyword tracking.",
  });
}

export async function listTargetKeywords(
  projectId: number | string,
  headers: AuthHeaders
): Promise<TargetKeyword[]> {
  return requestJson<TargetKeyword[]>({
    endpoint: `/api/v1/projects/${projectId}/monitoring/keywords`,
    method: "GET",
    headers,
    errorMessage: "Failed to load tracked keywords.",
  });
}

// SIGV2-1145: creating a tracked keyword from the approved SEO detail
// Keywords tab. The endpoint refuses a duplicate with its own sentence, and
// that sentence is what the dialog shows.
export async function createTargetKeyword(
  projectId: number | string,
  payload: CreateTargetKeywordPayload,
  headers: AuthHeaders
): Promise<TargetKeyword> {
  return requestJson<TargetKeyword>({
    endpoint: `/api/v1/projects/${projectId}/monitoring/keywords`,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Failed to add the keyword.",
  });
}

export async function fetchSearchConsolePages(
  projectId: number | string,
  headers: AuthHeaders,
  window = "7D"
): Promise<SearchConsolePagesResponse> {
  return requestJson<SearchConsolePagesResponse>({
    endpoint: `/api/v1/projects/${projectId}/monitoring/search-console/pages?window=${window}`,
    method: "GET",
    headers,
    errorMessage: "Failed to load Search Console pages.",
  });
}

export async function fetchAISearchVolatilitySummary(
  projectId: number | string,
  headers: AuthHeaders,
  options?: {
    provider?: string;
    days?: number;
  }
): Promise<VolatilitySummaryResponse> {
  const query = new URLSearchParams();
  if (options?.provider) {
    query.set("provider", options.provider);
  }
  if (typeof options?.days === "number") {
    query.set("days", String(options.days));
  }
  return requestJson<VolatilitySummaryResponse>({
    endpoint: `/api/v1/projects/${projectId}/monitoring/ai-search-volatility/summary${query.toString() ? `?${query.toString()}` : ""}`,
    method: "GET",
    headers,
    errorMessage: "Failed to load AI search volatility summary.",
  });
}

export async function fetchAISearchVolatilityTrends(
  projectId: number | string,
  headers: AuthHeaders,
  options?: {
    provider?: string;
    days?: number;
  }
): Promise<VolatilityTrendResponse> {
  const query = new URLSearchParams();
  if (options?.provider) {
    query.set("provider", options.provider);
  }
  if (typeof options?.days === "number") {
    query.set("days", String(options.days));
  }
  return requestJson<VolatilityTrendResponse>({
    endpoint: `/api/v1/projects/${projectId}/monitoring/ai-search-volatility/trends${query.toString() ? `?${query.toString()}` : ""}`,
    method: "GET",
    headers,
    errorMessage: "Failed to load AI search volatility trends.",
  });
}

export async function fetchPublicAISearchVolatilityDashboard(options?: {
  provider?: string;
  days?: number;
}): Promise<PublicVolatilityDashboardResponse> {
  const query = new URLSearchParams();
  if (options?.provider) {
    query.set("provider", options.provider);
  }
  if (typeof options?.days === "number") {
    query.set("days", String(options.days));
  }
  return requestJson<PublicVolatilityDashboardResponse>({
    endpoint: `/api/v1/volatility/public${query.toString() ? `?${query.toString()}` : ""}`,
    method: "GET",
    errorMessage: "Failed to load AI search volatility dashboard.",
  });
}

export async function fetchOffPageMentionsSummary(
  projectId: number | string,
  headers: AuthHeaders,
  days = 30
): Promise<OffPageMentionsSummaryResponse> {
  return requestJson<OffPageMentionsSummaryResponse>({
    endpoint: `/api/v1/projects/${projectId}/monitoring/off-page-mentions/summary?days=${days}`,
    method: "GET",
    headers,
    errorMessage: "Failed to load off-page mentions summary.",
  });
}

export async function fetchOffPageMentionsTrends(
  projectId: number | string,
  headers: AuthHeaders,
  days = 30
): Promise<OffPageMentionTrendResponse> {
  return requestJson<OffPageMentionTrendResponse>({
    endpoint: `/api/v1/projects/${projectId}/monitoring/off-page-mentions/trends?days=${days}`,
    method: "GET",
    headers,
    errorMessage: "Failed to load off-page mentions trends.",
  });
}

export async function fetchOffPageMentionsFeed(
  projectId: number | string,
  headers: AuthHeaders,
  options?: {
    days?: number;
    limit?: number;
    sentiment?: "positive" | "neutral" | "negative";
  }
): Promise<OffPageMentionFeedItem[]> {
  const query = new URLSearchParams();
  if (typeof options?.days === "number") {
    query.set("days", String(options.days));
  }
  if (typeof options?.limit === "number") {
    query.set("limit", String(options.limit));
  }
  if (options?.sentiment) {
    query.set("sentiment", options.sentiment);
  }
  return requestJson<OffPageMentionFeedItem[]>({
    endpoint: `/api/v1/projects/${projectId}/monitoring/off-page-mentions/feed${query.toString() ? `?${query.toString()}` : ""}`,
    method: "GET",
    headers,
    errorMessage: "Failed to load off-page mentions feed.",
  });
}

// SIGV2-1035: GET /api/v1/projects/{id}/monitoring/site-traffic?window=.
// The response is a union: a full payload on success, or a {status} stub for
// disconnected / revoked / provider_error (docs/ga4-reporting-contract.md).
export async function fetchSiteTraffic(
  projectId: number | string,
  window: SiteTrafficWindow,
  headers: AuthHeaders
): Promise<SiteTrafficResponse> {
  return requestJson<SiteTrafficResponse>({
    endpoint: `/api/v1/projects/${projectId}/monitoring/site-traffic?window=${window}`,
    method: "GET",
    headers,
    errorMessage: "Failed to load site traffic.",
  });
}
