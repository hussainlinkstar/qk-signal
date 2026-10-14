"use client";

import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import { requestJson } from "@/services/http";

export type ActiveAuditJob = {
  job_id: string;
  status: string;
  audit_target_type: string;
  target_name: string | null;
  target_url: string | null;
  tier: string | null;
  tier_display: string | null;
  started_at: string | null;
  last_heartbeat: string | null;
  stale: boolean;
  stale_reason: string | null;
  project_id: number | null;
};

type ActiveAuditJobsResponse = {
  jobs: ActiveAuditJob[];
};

const POLL_INTERVAL_MS = 15_000;

/**
 * Polls `GET /api/audit/jobs` (proxied to `/api/v1/audit/jobs/active`)
 * to discover the current user's queued/running audit jobs.
 *
 * Useful for showing an in-progress indicator in the TopBar and
 * enabling re-attachment to a running audit's SSE stream.
 */
export function useActiveAudits() {
  const { isSignedIn } = useAuth();

  const query = useQuery<ActiveAuditJobsResponse>({
    queryKey: ["active-audits"],
    queryFn: async () => {
      const data = await requestJson<ActiveAuditJobsResponse>({
        endpoint: "/api/audit/jobs",
        method: "GET",
        errorMessage: "Failed to fetch active audits",
      });
      return data;
    },
    enabled: !!isSignedIn,
    refetchInterval: POLL_INTERVAL_MS,
    staleTime: 10_000,
  });

  const activeJobs = query.data?.jobs ?? [];

  return {
    activeJobs,
    hasActiveAudits: activeJobs.length > 0,
    isLoading: query.isLoading,
    refetch: query.refetch,
  };
}
