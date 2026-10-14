"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/auth/custom-auth";
import { requestJson } from "@/services/http";
import type { UsageAnalyticsResponse } from "@/types/billing";

export function useScanUsage(days: number = 30) {
  const { isSignedIn, isLoading: authLoading } = useAuth();
  const [data, setData] = useState<UsageAnalyticsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await requestJson<UsageAnalyticsResponse>({
        endpoint: `/api/billing/usage-analytics?days=${days}`,
        method: "GET",
        errorMessage: "Failed to load usage analytics",
      });
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load usage data");
    } finally {
      setIsLoading(false);
    }
  }, [days]);

  useEffect(() => {
    if (isSignedIn && !authLoading) {
      void load();
    }
  }, [isSignedIn, authLoading, load]);

  return { data, isLoading, error, reload: load };
}
