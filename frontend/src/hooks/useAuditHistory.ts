"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/components/auth/custom-auth";
import { generateAiStrategicInsights } from "@/services/ai/aiStrategicInsightsService";
import { fetchAuditHistory, mapAuditHistoryToViewModel } from "@/services/auditService";
import {
  DEFAULT_AI_STRATEGIC_INSIGHTS,
  type AiStrategicInsights,
  type AiStrategistViewModel,
} from "@/types/aiStrategist";
import { belongsToProject } from "@/lib/auditListUtils";

type UseAuditHistoryResult = {
  data: AiStrategistViewModel[];
  latest: AiStrategistViewModel | null;
  loading: boolean;
  error: string | null;
  aiLoading: boolean;
  aiError: string | null;
  aiWarning: string | null;
  lastAiRefresh: string | null;
  refetch: () => Promise<void>;
  refreshAiInsights: () => Promise<void>;
};

const DEFAULT_HEADERS: HeadersInit = {};
type LatestInsightContext = {
  auditId: number;
  projectId?: number | null;
};

const mergeLatestInsights = (
  model: AiStrategistViewModel[],
  insights: AiStrategicInsights
): AiStrategistViewModel[] => {
  if (!model.length) return model;

  const copy = [...model];
  const lastIndex = copy.length - 1;
  copy[lastIndex] = { ...copy[lastIndex], aiInsights: insights };
  return copy;
};

export const useAuditHistory = (headers: HeadersInit = DEFAULT_HEADERS): UseAuditHistoryResult => {
  const searchParams = useSearchParams();
  const { getToken, isSignedIn } = useAuth();
  const [data, setData] = useState<AiStrategistViewModel[]>([]);
  const [latestInsightContext, setLatestInsightContext] = useState<LatestInsightContext | null>(
    null
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [aiWarning, setAiWarning] = useState<string | null>(null);
  const [lastAiRefresh, setLastAiRefresh] = useState<string | null>(null);
  const providedHeaders = useMemo(() => headers, [headers]);
  const rawProjectId = searchParams?.get("projectId") ?? searchParams?.get("siteId");
  const selectedProjectId = useMemo(() => {
    if (!rawProjectId) {
      return undefined;
    }

    const parsed = Number(rawProjectId);
    return Number.isInteger(parsed) ? parsed : undefined;
  }, [rawProjectId]);
  const previousProjectIdRef = useRef<number | undefined>(selectedProjectId);

  const getHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to view SEO dashboard data.");
    }

    return { ...providedHeaders, Authorization: `Bearer ${token}` };
  }, [getToken, providedHeaders]);

  const refreshAiInsightsForAuditData = useCallback(
    async (context: LatestInsightContext | null) => {
      if (!context) return;

      setAiLoading(true);
      setAiError(null);
      setAiWarning(null);

      try {
        const generatedInsights = await generateAiStrategicInsights({
          auditId: context.auditId,
          projectId: context.projectId,
        });
        if (!generatedInsights) {
          setData((prev) => mergeLatestInsights(prev, DEFAULT_AI_STRATEGIC_INSIGHTS));
          setLastAiRefresh(new Date().toISOString());
          setAiWarning(
            "Grounded strategic insights were unavailable, so placeholder data is shown."
          );
          return;
        }

        setData((prev) => mergeLatestInsights(prev, generatedInsights));
        setLastAiRefresh(generatedInsights.generated_at ?? new Date().toISOString());
      } catch (e) {
        setAiError("Unable to refresh grounded strategic insights right now. Please try again.");
        setData((prev) => mergeLatestInsights(prev, DEFAULT_AI_STRATEGIC_INSIGHTS));
        setLastAiRefresh(new Date().toISOString());
      } finally {
        setAiLoading(false);
      }
    },
    []
  );

  const refreshAiInsights = useCallback(async () => {
    await refreshAiInsightsForAuditData(latestInsightContext);
  }, [latestInsightContext, refreshAiInsightsForAuditData]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (!isSignedIn) {
        throw new Error("Please sign in to load assessment history.");
      }

      const authHeaders = await getHeaders();
      const raw = await fetchAuditHistory(authHeaders, selectedProjectId);
      const filteredByProject =
        typeof selectedProjectId === "number"
          ? raw.filter((entry) => belongsToProject(entry, selectedProjectId))
          : raw;
      const filteredRaw =
        typeof selectedProjectId === "number" && raw.length > 0 && filteredByProject.length === 0
          ? raw
          : filteredByProject;
      const mapped = mapAuditHistoryToViewModel(filteredRaw);
      setData(mapped);

      const latestRaw = filteredRaw.length ? (filteredRaw[filteredRaw.length - 1] ?? null) : null;
      const latestContext =
        latestRaw && typeof latestRaw.id === "number"
          ? {
              auditId: latestRaw.id,
              projectId:
                typeof latestRaw.project_id === "number" ? latestRaw.project_id : undefined,
            }
          : null;
      setLatestInsightContext(latestContext);

      if (latestContext) {
        await refreshAiInsightsForAuditData(latestContext);
      }
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Unexpected error while loading assessment history."
      );
      setData([]);
      setLatestInsightContext(null);
    } finally {
      setLoading(false);
    }
  }, [getHeaders, isSignedIn, refreshAiInsightsForAuditData, selectedProjectId]);

  useEffect(() => {
    if (previousProjectIdRef.current === selectedProjectId) {
      return;
    }

    previousProjectIdRef.current = selectedProjectId;
    setLoading(true);
    setData([]);
    setLatestInsightContext(null);
    setAiError(null);
    setAiWarning(null);
  }, [selectedProjectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const latest = useMemo(() => (data.length ? data[data.length - 1] : null), [data]);

  return {
    data,
    latest,
    loading,
    error,
    aiLoading,
    aiError,
    aiWarning,
    lastAiRefresh,
    refetch: load,
    refreshAiInsights,
  };
};
