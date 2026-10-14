import { requestJson } from "@/services/http";

export type ClaimReviewDisposition = "manually_approved" | "manually_refused";
export type ClaimReviewStatusFilter = "all" | "pending" | "approved" | "refused";
export type ClaimReviewDomainFilter = "all" | "seo" | "geo" | "aeo" | "general";

export type ClaimReviewDecision = {
  id: number;
  audit_id: number;
  project_id: number;
  claim_id: string;
  claim_domain: string;
  claim_text: string;
  original_disposition: string;
  review_disposition: ClaimReviewDisposition;
  review_note: string | null;
  reviewed_by_id: number | null;
  reviewed_by_display_name: string | null;
  reviewed_at: string;
  schema_version: string;
};

export type ClaimReviewQueueItem = {
  claim_id: string;
  domain: string;
  claim_text: string;
  current_disposition: "needs_manual_review" | ClaimReviewDisposition;
  confidence_score: number | null;
  confidence_band: string | null;
  critique_reference: string | null;
  evidence_anchor_excerpt: Record<string, unknown> | null;
  reason_codes: string[];
  problem_refs: string[];
  evidence_refs: string[];
  suggested_rewrite: string | null;
  review_decision: ClaimReviewDecision | null;
};

export type ClaimReviewQueueResponse = {
  audit_id: number;
  total_flagged: number;
  reviewed: number;
  approved_count: number;
  refused_count: number;
  pending: number;
  can_review: boolean;
  claims: ClaimReviewQueueItem[];
};

export type ClaimReviewSummaryResponse = {
  audit_id: number;
  total_flagged: number;
  approved_count: number;
  refused_count: number;
  pending_count: number;
  impact: {
    score_recalculated: boolean;
    export_excluded_claims: number;
    note: string;
  };
};

export async function fetchClaimReviewQueue(
  auditId: number | string,
  headers: HeadersInit = {}
): Promise<ClaimReviewQueueResponse> {
  return requestJson<ClaimReviewQueueResponse>({
    endpoint: `/api/v1/audits/${auditId}/review-queue`,
    method: "GET",
    headers,
    errorMessage: "Unable to load the claim review queue.",
  });
}

export async function submitClaimReview(
  auditId: number | string,
  claimId: string,
  body: {
    disposition: ClaimReviewDisposition;
    note?: string | null;
  },
  headers: HeadersInit = {}
): Promise<ClaimReviewDecision> {
  return requestJson<ClaimReviewDecision>({
    endpoint: `/api/v1/audits/${auditId}/claims/${encodeURIComponent(claimId)}/review`,
    method: "POST",
    headers,
    body,
    errorMessage: "Unable to save the claim review decision.",
  });
}

export async function fetchClaimReviewSummary(
  auditId: number | string,
  headers: HeadersInit = {}
): Promise<ClaimReviewSummaryResponse> {
  return requestJson<ClaimReviewSummaryResponse>({
    endpoint: `/api/v1/audits/${auditId}/review-summary`,
    method: "GET",
    headers,
    errorMessage: "Unable to load the claim review summary.",
  });
}
