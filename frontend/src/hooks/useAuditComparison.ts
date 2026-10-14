/**
 * Audit Comparison types and hook, AEX-19
 *
 * Fetches score delta comparison data for an audit vs its predecessor.
 */

import { useQuery } from "@tanstack/react-query";
import { requestJson } from "@/services/http";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ScoreDelta = {
  current: number | null;
  previous?: number | null;
  delta?: number | null;
  direction?: "up" | "down" | "stable";
};

export type SubComponentDelta = {
  current: number | null;
  previous: number | null;
  delta: number | null;
  direction: "up" | "down" | "stable";
};

export type AuditComparisonHistoryPoint = {
  audit_id: number;
  date: string;
  overall: number | null;
  seo: number | null;
  geo: number | null;
  aeo: number | null;
};

export type AuditComparisonResponse = {
  audit_id: number;
  has_previous: boolean;
  previous_audit_id?: number;
  previous_audit_date?: string;
  scores: Record<"overall" | "seo" | "geo" | "aeo", ScoreDelta>;
  sub_components: Record<string, Record<string, SubComponentDelta>>;
  history: AuditComparisonHistoryPoint[];
};

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useAuditComparison(auditId: number | null | undefined) {
  return useQuery<AuditComparisonResponse>({
    queryKey: ["audit-comparison", auditId],
    queryFn: () =>
      requestJson<AuditComparisonResponse>({
        endpoint: `/api/audit/${auditId}/comparison`,
        method: "GET",
        errorMessage: "Failed to fetch audit comparison",
      }),
    enabled: !!auditId,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });
}
