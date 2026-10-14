"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CloudLightning,
  RefreshCcw,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
  Wind,
} from "lucide-react";

import PlanLockNotice from "@/components/dashboard/PlanLockNotice";
import ProjectMonitoringSection, {
  ProjectMonitoringAlert,
  ProjectMonitoringEmptyState,
  ProjectMonitoringLoadingState,
  ProjectMonitoringMetricCard,
  ProjectMonitoringStateCard,
} from "@/components/dashboard/ProjectMonitoringSection";
import { useAuth } from "@/components/auth/custom-auth";
import Button from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassComponents";
import { getPlanLockContent, isPlanUpgradeError } from "@/lib/planLocks";
import {
  fetchAISearchVolatilitySummary,
  fetchAISearchVolatilityTrends,
} from "@/services/monitoringService";
import type { VolatilitySummaryResponse, VolatilityTrendResponse } from "@/types/monitoring";

type ProjectVolatilityIndexPanelProps = {
  projectId: number | string;
};

const formatDate = (value: string | null) => {
  if (!value) {
    return "N/A";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
};

const formatPercent = (value: number | null, precision = 1) => {
  if (value === null) {
    return "N/A";
  }
  return `${(value * 100).toFixed(precision)}%`;
};

export default function ProjectVolatilityIndexPanel({
  projectId,
}: ProjectVolatilityIndexPanelProps) {
  const { getToken } = useAuth();
  const [summary, setSummary] = useState<VolatilitySummaryResponse | null>(null);
  const [trends, setTrends] = useState<VolatilityTrendResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [planLocked, setPlanLocked] = useState(false);
  const [permissionDenied, setPermissionDenied] = useState(false);

  const buildHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, [getToken]);

  const loadData = useCallback(
    async (mode: "initial" | "refresh" = "initial") => {
      if (mode === "initial") {
        setLoading(true);
      } else {
        setRefreshing(true);
      }
      setError(null);
      setPlanLocked(false);
      setPermissionDenied(false);
      try {
        const headers = await buildHeaders();
        const [summaryPayload, trendsPayload] = await Promise.all([
          fetchAISearchVolatilitySummary(projectId, headers, { provider: "all", days: 30 }),
          fetchAISearchVolatilityTrends(projectId, headers, { provider: "all", days: 30 }),
        ]);
        setSummary(summaryPayload);
        setTrends(trendsPayload);
      } catch (loadError) {
        const message =
          loadError instanceof Error
            ? loadError.message
            : "Unable to load AI search volatility index.";
        const normalized = message.toLowerCase();
        if (isPlanUpgradeError(loadError)) {
          setPlanLocked(true);
        } else if (normalized.includes("access denied") || normalized.includes("not authorized")) {
          setPermissionDenied(true);
        } else {
          setError(message);
        }
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [buildHeaders, projectId]
  );

  useEffect(() => {
    void loadData("initial");
  }, [loadData]);

  const trendDelta = useMemo(() => {
    if (!trends || trends.points.length < 2) {
      return null;
    }
    const points = trends.points.filter((point) => typeof point.volatility_score === "number");
    if (points.length < 2) {
      return null;
    }
    const first = points[0].volatility_score ?? 0;
    const last = points[points.length - 1].volatility_score ?? 0;
    return Number((last - first).toFixed(2));
  }, [trends]);
  const planLockContent = getPlanLockContent("aiSearchVolatility");

  if (loading) {
    return <ProjectMonitoringLoadingState label="Loading AI search volatility..." />;
  }

  if (planLocked) {
    return <PlanLockNotice {...planLockContent} />;
  }

  if (permissionDenied) {
    return (
      <ProjectMonitoringStateCard
        icon={ShieldAlert}
        title="Access Limited"
        description="You have limited access for this project monitoring surface."
      />
    );
  }

  if (error) {
    return (
      <ProjectMonitoringStateCard
        icon={AlertTriangle}
        title="Volatility Index Unavailable"
        description={error}
        tone="rose"
        action={
          <Button variant="ghost" onClick={() => void loadData("refresh")} loading={refreshing}>
            <RefreshCcw className="h-4 w-4" /> Retry
          </Button>
        }
      />
    );
  }

  if (!summary || summary.no_data) {
    return (
      <ProjectMonitoringEmptyState
        icon={CloudLightning}
        title="No Volatility Baseline Yet"
        description="Global seed queries need at least two daily runs before volatility scoring is available."
        action={
          <Button variant="ghost" onClick={() => void loadData("refresh")} loading={refreshing}>
            <RefreshCcw className="h-4 w-4" /> Refresh
          </Button>
        }
      />
    );
  }

  return (
    <ProjectMonitoringSection
      id="ai-search-volatility"
      icon={CloudLightning}
      title="AI Search"
      accent="Volatility Index"
      description="Correlate global LLM answer turbulence with project trend movement and explain sudden visibility changes."
      action={
        <Button variant="ghost" onClick={() => void loadData("refresh")} loading={refreshing}>
          <RefreshCcw className="h-4 w-4" /> Refresh
        </Button>
      }
    >
      {summary.degraded ? (
        <ProjectMonitoringAlert
          icon={ShieldAlert}
          title="Volatility signal is degraded."
          description={summary.degraded_reasons.join("; ") || "Data quality warning detected."}
        />
      ) : null}

      <div className="grid gap-4 md:grid-cols-4">
        <ProjectMonitoringMetricCard
          label="Volatility Score"
          value={
            <p className="text-3xl font-black text-(--t-1)">
              {summary.volatility_score === null
                ? "N/A"
                : `${summary.volatility_score.toFixed(2)}/10`}
            </p>
          }
        />
        <ProjectMonitoringMetricCard
          label="Weather"
          value={
            <p className="text-3xl font-black capitalize text-(--t-1)">{summary.weather_label}</p>
          }
        />
        <ProjectMonitoringMetricCard
          label="Compared Queries"
          value={<p className="text-3xl font-black text-(--t-1)">{summary.compared_queries}</p>}
        />
        <ProjectMonitoringMetricCard
          label="30-Day Delta"
          value={
            <div className="flex items-center gap-2">
              {trendDelta !== null && trendDelta > 0 ? (
                <TrendingUp className="h-5 w-5 text-rose-300" />
              ) : trendDelta !== null && trendDelta < 0 ? (
                <TrendingDown className="h-5 w-5 text-emerald-300" />
              ) : (
                <Wind className="h-5 w-5 text-(--t-2)" />
              )}
              <p className="text-2xl font-black text-(--t-1)">
                {trendDelta === null
                  ? "N/A"
                  : `${trendDelta > 0 ? "+" : ""}${trendDelta.toFixed(2)}`}
              </p>
            </div>
          }
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <GlassCard className="space-y-4 p-5">
          <p className="text-[10px] font-black uppercase tracking-widest text-(--t-3)">
            Signal Components ({formatDate(summary.latest_snapshot_date)})
          </p>
          <div className="space-y-2 text-xs text-(--t-2)">
            <div className="flex items-center justify-between rounded-lg border border-(--line) bg-(--line-2) px-3 py-2">
              <span>Changed queries</span>
              <span>{formatPercent(summary.changed_ratio, 2)}</span>
            </div>
            <div className="flex items-center justify-between rounded-lg border border-(--line) bg-(--line-2) px-3 py-2">
              <span>Avg text similarity</span>
              <span>
                {summary.avg_text_similarity === null
                  ? "N/A"
                  : summary.avg_text_similarity.toFixed(3)}
              </span>
            </div>
            <div className="flex items-center justify-between rounded-lg border border-(--line) bg-(--line-2) px-3 py-2">
              <span>Avg citation jaccard</span>
              <span>
                {summary.avg_citation_jaccard === null
                  ? "N/A"
                  : summary.avg_citation_jaccard.toFixed(3)}
              </span>
            </div>
            <div className="flex items-center justify-between rounded-lg border border-(--line) bg-(--line-2) px-3 py-2">
              <span>Citation churn</span>
              <span>{formatPercent(summary.citation_churn_rate, 2)}</span>
            </div>
            <div className="flex items-center justify-between rounded-lg border border-(--line) bg-(--line-2) px-3 py-2">
              <span>Format change rate</span>
              <span>{formatPercent(summary.format_change_rate, 2)}</span>
            </div>
          </div>
        </GlassCard>

        <GlassCard className="space-y-4 p-5">
          <p className="text-[10px] font-black uppercase tracking-widest text-(--t-3)">
            Industry Breakdown
          </p>
          {summary.industries.length === 0 ? (
            <p className="text-sm text-(--t-2)">No industry slices available for this run.</p>
          ) : (
            <div className="space-y-2">
              {summary.industries.slice(0, 8).map((item) => (
                <div
                  key={item.industry}
                  className="flex items-center justify-between rounded-lg border border-(--line) bg-(--line-2) px-3 py-2 text-xs text-(--t-2)"
                >
                  <span className="font-semibold capitalize text-(--t-1)">{item.industry}</span>
                  <span>
                    {item.volatility_score === null
                      ? "N/A"
                      : `${item.volatility_score.toFixed(2)}/10`}
                  </span>
                  <span>{item.compared_queries} queries</span>
                </div>
              ))}
            </div>
          )}
        </GlassCard>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <GlassCard className="space-y-4 p-5 lg:col-span-2">
          <p className="text-[10px] font-black uppercase tracking-widest text-(--t-3)">
            30-Day Volatility Trend
          </p>
          {!trends || trends.points.length === 0 ? (
            <p className="text-sm text-(--t-2)">No trend points available.</p>
          ) : (
            <div className="space-y-2">
              {trends.points.slice(-10).map((point) => (
                <div
                  key={point.date}
                  className="flex items-center justify-between rounded-lg border border-(--line) bg-(--line-2) px-3 py-2 text-xs text-(--t-2)"
                >
                  <span>{formatDate(point.date)}</span>
                  <span>
                    {point.volatility_score === null
                      ? "N/A"
                      : `${point.volatility_score.toFixed(2)}/10`}
                  </span>
                  <span>{point.compared_queries} queries</span>
                </div>
              ))}
            </div>
          )}
        </GlassCard>

        <GlassCard className="space-y-4 p-5">
          <p className="text-[10px] font-black uppercase tracking-widest text-(--t-3)">
            Citation Domain Movers
          </p>
          <div className="space-y-3">
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-emerald-300">
                Top Winners
              </p>
              {summary.top_winners.length === 0 ? (
                <p className="text-xs text-(--t-2)">No gainers in this window.</p>
              ) : (
                <div className="space-y-1">
                  {summary.top_winners.slice(0, 5).map((item) => (
                    <div
                      key={`winner-${item.domain}`}
                      className="flex items-center justify-between rounded-lg border border-(--line) bg-(--line-2) px-3 py-2 text-xs text-(--t-2)"
                    >
                      <span>{item.domain}</span>
                      <span>+{item.delta}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-rose-300">
                Top Losers
              </p>
              {summary.top_losers.length === 0 ? (
                <p className="text-xs text-(--t-2)">No losers in this window.</p>
              ) : (
                <div className="space-y-1">
                  {summary.top_losers.slice(0, 5).map((item) => (
                    <div
                      key={`loser-${item.domain}`}
                      className="flex items-center justify-between rounded-lg border border-(--line) bg-(--line-2) px-3 py-2 text-xs text-(--t-2)"
                    >
                      <span>{item.domain}</span>
                      <span>-{item.delta}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </GlassCard>
      </div>
    </ProjectMonitoringSection>
  );
}
