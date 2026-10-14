"use client";

import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/custom-auth";
import AIVisibilityScoreCard from "@/components/dashboard/AIVisibilityScoreCard";
import VisibilityQueryGrid from "@/components/dashboard/VisibilityQueryGrid";
import VisibilityQueryManager from "@/components/dashboard/VisibilityQueryManager";
import VisibilitySearchTypeCoverage from "@/components/dashboard/VisibilitySearchTypeCoverage";
import VisibilityTrendChart from "@/components/dashboard/VisibilityTrendChart";
import {
  createVisibilityQuery,
  deleteVisibilityQuery,
  fetchVisibilityQueries,
  fetchVisibilitySummary,
  fetchVisibilityTrends,
  generateBaseVisibilityPrompts,
  updateVisibilityQuery,
} from "@/services/monitoringService";
import type {
  SearchTypeCoverageEntry,
  UpdateVisibilityQueryPayload,
  VisibilityEntitlements,
  VisibilityQueryListResponse,
  VisibilitySummaryResponse,
  VisibilityTrendResponse,
} from "@/types/monitoring";

type ProjectVisibilityPanelProps = {
  projectId: number | string;
};

export default function ProjectVisibilityPanel({ projectId }: ProjectVisibilityPanelProps) {
  const { getToken } = useAuth();
  const [queryList, setQueryList] = useState<VisibilityQueryListResponse | null>(null);
  const [summary, setSummary] = useState<VisibilitySummaryResponse | null>(null);
  const [trends, setTrends] = useState<VisibilityTrendResponse | null>(null);
  const [queriesLoading, setQueriesLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [trendsLoading, setTrendsLoading] = useState(true);
  const [queriesError, setQueriesError] = useState<string | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [trendsError, setTrendsError] = useState<string | null>(null);

  const buildHeaders = useCallback(async () => {
    const token = await getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, [getToken]);

  const loadQueries = useCallback(async () => {
    setQueriesLoading(true);
    setQueriesError(null);
    try {
      const headers = await buildHeaders();
      setQueryList(await fetchVisibilityQueries(projectId, headers));
    } catch (error) {
      setQueriesError(
        error instanceof Error ? error.message : "Failed to load visibility queries."
      );
    } finally {
      setQueriesLoading(false);
    }
  }, [buildHeaders, projectId]);

  const loadSummary = useCallback(async () => {
    setSummaryLoading(true);
    setSummaryError(null);
    try {
      const headers = await buildHeaders();
      setSummary(await fetchVisibilitySummary(projectId, headers));
    } catch (error) {
      setSummaryError(
        error instanceof Error ? error.message : "Failed to load AI visibility summary."
      );
    } finally {
      setSummaryLoading(false);
    }
  }, [buildHeaders, projectId]);

  const loadTrends = useCallback(async () => {
    setTrendsLoading(true);
    setTrendsError(null);
    try {
      const headers = await buildHeaders();
      setTrends(await fetchVisibilityTrends(projectId, headers, 30));
    } catch (error) {
      setTrendsError(
        error instanceof Error ? error.message : "Failed to load AI visibility trends."
      );
    } finally {
      setTrendsLoading(false);
    }
  }, [buildHeaders, projectId]);

  const refreshAll = useCallback(async () => {
    await Promise.all([loadQueries(), loadSummary(), loadTrends()]);
  }, [loadQueries, loadSummary, loadTrends]);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  const handleUpdate = useCallback(
    async (queryId: number, payload: UpdateVisibilityQueryPayload) => {
      try {
        const headers = await buildHeaders();
        await updateVisibilityQuery(projectId, queryId, payload, headers);
        toast.success("Visibility query updated.");
        await refreshAll();
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "Failed to update visibility query.");
        throw error;
      }
    },
    [buildHeaders, projectId, refreshAll]
  );

  const handleDelete = useCallback(
    async (queryId: number) => {
      try {
        const headers = await buildHeaders();
        await deleteVisibilityQuery(projectId, queryId, headers);
        toast.success("Visibility query removed.");
        await refreshAll();
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "Failed to remove visibility query.");
        throw error;
      }
    },
    [buildHeaders, projectId, refreshAll]
  );

  // SIGV2-1186: filling a gap creates one prompt for each uncovered search
  // type. The backend is idempotent and plan-bounded, so there is nothing to
  // guard here beyond reporting what it did; `reason` is its own sentence when
  // it created nothing, never a silent success.
  const handleGenerateBase = useCallback(async () => {
    try {
      const headers = await buildHeaders();
      const result = await generateBaseVisibilityPrompts(projectId, headers);
      if (result.created.length > 0) {
        toast.success(
          `Added ${result.created.length} ${result.created.length === 1 ? "prompt" : "prompts"}.`
        );
      } else if (result.reason === "plan_locked") {
        toast.error("Prompt tracking is not included on this plan.");
      } else if (result.reason === "cap_reached") {
        toast.error("Your prompt allowance is fully used.");
      } else if (result.reason === "already_covered") {
        toast.success("Every search type is already covered.");
      } else {
        toast.error("No prompts could be added.");
      }
      await refreshAll();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to generate base prompts.");
    }
  }, [buildHeaders, projectId, refreshAll]);

  // SIGV2-1186: one gap, filled with the exact sentence the customer was shown
  // and the type it was written for. It is created as the customer's own prompt
  // (not origin="generated"): they chose to add this one, where the bulk action
  // above is Signal adding prompts on their behalf.
  const handleFillGap = useCallback(
    async (entry: SearchTypeCoverageEntry) => {
      if (!entry.suggested_prompt) return;
      try {
        const headers = await buildHeaders();
        await createVisibilityQuery(
          projectId,
          {
            query_text: entry.suggested_prompt,
            query_type: "aeo",
            // Empty selection means "the first engine the plan allows", which
            // is the same default the API applies to a manual add.
            providers: [],
            search_type: entry.id,
          },
          headers
        );
        toast.success(`Added a ${entry.label.toLowerCase()} prompt.`);
        await refreshAll();
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "Failed to add the prompt.");
      }
    },
    [buildHeaders, projectId, refreshAll]
  );

  const entitlements: VisibilityEntitlements | null =
    summary?.entitlements ?? queryList?.entitlements ?? null;
  const capReached = Boolean(
    entitlements && entitlements.max_queries > 0 && entitlements.remaining_queries <= 0
  );

  return (
    // SIGV2-1142: creating a prompt now happens on the approved AIO detail
    // Prompts tab. What is left here is management of prompts that exist, and
    // the anchor is what the refusal dialog links to.
    <div id="tracked-prompts" className="space-y-6">
      <AIVisibilityScoreCard
        summary={summary}
        loading={summaryLoading}
        error={summaryError}
        onRetry={() => void loadSummary()}
      />
      {/* SIGV2-1186: which of the five search types the project's prompts
          actually cover, stated before a scan runs. */}
      <VisibilitySearchTypeCoverage
        coverage={queryList?.coverage ?? []}
        loading={queriesLoading}
        onGenerateAll={handleGenerateBase}
        onFillGap={handleFillGap}
        capReached={capReached}
        locked={entitlements?.is_locked === true}
      />
      <VisibilityQueryManager
        projectId={projectId}
        queries={queryList?.queries ?? []}
        entitlements={entitlements}
        loading={queriesLoading}
        error={queriesError}
        onUpdate={handleUpdate}
        onDelete={handleDelete}
      />
      <VisibilityQueryGrid summary={summary} loading={summaryLoading} error={summaryError} />
      {/* SIGV2-1216: the chart is fed by recorded cells, so it needs the
          plan's roster to know which of them are still being measured. */}
      <VisibilityTrendChart
        trends={trends}
        allowedProviders={entitlements?.allowed_providers ?? null}
        loading={trendsLoading}
        error={trendsError}
      />
    </div>
  );
}
