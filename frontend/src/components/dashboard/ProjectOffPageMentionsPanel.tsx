"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ExternalLink,
  Globe,
  MessageSquareQuote,
  RefreshCcw,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
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
  fetchOffPageMentionsFeed,
  fetchOffPageMentionsSummary,
  fetchOffPageMentionsTrends,
} from "@/services/monitoringService";
import type {
  OffPageMentionFeedItem,
  OffPageMentionTrendResponse,
  OffPageMentionsSummaryResponse,
} from "@/types/monitoring";

type ProjectOffPageMentionsPanelProps = {
  projectId: number | string;
};

const formatNumber = (value: number) => new Intl.NumberFormat("en-US").format(value);

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

export default function ProjectOffPageMentionsPanel({
  projectId,
}: ProjectOffPageMentionsPanelProps) {
  const { getToken } = useAuth();
  const [summary, setSummary] = useState<OffPageMentionsSummaryResponse | null>(null);
  const [trends, setTrends] = useState<OffPageMentionTrendResponse | null>(null);
  const [feed, setFeed] = useState<OffPageMentionFeedItem[]>([]);
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
        const [summaryPayload, trendsPayload, feedPayload] = await Promise.all([
          fetchOffPageMentionsSummary(projectId, headers, 30),
          fetchOffPageMentionsTrends(projectId, headers, 30),
          fetchOffPageMentionsFeed(projectId, headers, { days: 30, limit: 20 }),
        ]);
        setSummary(summaryPayload);
        setTrends(trendsPayload);
        setFeed(feedPayload);
      } catch (loadError) {
        const message =
          loadError instanceof Error
            ? loadError.message
            : "Unable to load off-page mentions tracker.";
        const normalized = message.toLowerCase();
        if (isPlanUpgradeError(loadError)) {
          setPlanLocked(true);
        } else if (
          normalized.includes("access denied") ||
          normalized.includes("not authorized") ||
          normalized.includes("workspace write access")
        ) {
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

  const trendDirection = useMemo(() => {
    if (!summary || summary.trend_delta === null) {
      return "flat";
    }
    if (summary.trend_delta > 0) {
      return "up";
    }
    if (summary.trend_delta < 0) {
      return "down";
    }
    return "flat";
  }, [summary]);
  const planLockContent = getPlanLockContent("offPageMentions");

  if (loading) {
    return <ProjectMonitoringLoadingState label="Loading off-page mentions tracker..." />;
  }

  if (planLocked) {
    return <PlanLockNotice {...planLockContent} />;
  }

  if (permissionDenied) {
    return (
      <ProjectMonitoringStateCard
        icon={ShieldAlert}
        title="Access Limited"
        description="You have read-only or limited access for this project monitoring surface."
      />
    );
  }

  if (error) {
    return (
      <ProjectMonitoringStateCard
        icon={AlertTriangle}
        title="Off-Page Mentions Unavailable"
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
        icon={MessageSquareQuote}
        title="No Off-Page Mentions Yet"
        description="Mentions will appear after ingesting Reddit/news observations for this project."
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
      id="off-page-mentions"
      icon={MessageSquareQuote}
      title="Off-Page"
      accent="AI answers mentions"
      description="Track brand mentions on high-trust LLM corpus domains, sentiment, and entity associations."
      action={
        <Button variant="ghost" onClick={() => void loadData("refresh")} loading={refreshing}>
          <RefreshCcw className="h-4 w-4" /> Refresh
        </Button>
      }
    >
      {summary.degraded ? (
        <ProjectMonitoringAlert
          icon={ShieldAlert}
          title="Mentions analysis is partially degraded."
          description={summary.degraded_reasons.join("; ") || "Data quality warning detected."}
        />
      ) : null}

      <div className="grid gap-4 md:grid-cols-4">
        <ProjectMonitoringMetricCard
          label="Off-Page Answer Engine Index"
          value={
            <p className="text-3xl font-black text-(--t-1)">
              {summary.off_page_aeo_score.toFixed(2)}%
            </p>
          }
        />
        <ProjectMonitoringMetricCard
          label="Mentions"
          value={
            <p className="text-3xl font-black text-(--t-1)">
              {formatNumber(summary.totals.total_mentions)}
            </p>
          }
        />
        <ProjectMonitoringMetricCard
          label="Unique Domains"
          value={
            <p className="text-3xl font-black text-(--t-1)">
              {formatNumber(summary.totals.unique_domains)}
            </p>
          }
        />
        <ProjectMonitoringMetricCard
          label="Trend Delta"
          value={
            <div className="flex items-center gap-2">
              {trendDirection === "up" ? (
                <TrendingUp className="h-5 w-5 text-emerald-300" />
              ) : trendDirection === "down" ? (
                <TrendingDown className="h-5 w-5 text-rose-300" />
              ) : (
                <Globe className="h-5 w-5 text-(--t-2)" />
              )}
              <p className="text-2xl font-black text-(--t-1)">
                {summary.trend_delta === null
                  ? "N/A"
                  : `${summary.trend_delta > 0 ? "+" : ""}${summary.trend_delta.toFixed(2)}%`}
              </p>
            </div>
          }
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <GlassCard className="space-y-4 p-5 lg:col-span-2">
          <p className="text-[10px] font-black uppercase tracking-widest text-(--t-3)">
            Top Domains
          </p>
          {summary.top_domains.length === 0 ? (
            <p className="text-sm text-(--t-2)">No domain coverage in this window.</p>
          ) : (
            <div className="space-y-2">
              {summary.top_domains.map((domain) => (
                <div
                  key={domain.domain}
                  className="flex items-center justify-between rounded-xl border-0 bg-(--line-2) px-4 py-3"
                >
                  <div>
                    <p className="text-sm font-semibold text-(--t-1)">{domain.domain}</p>
                    <p className="text-xs text-(--t-2)">{formatNumber(domain.mentions)} mentions</p>
                  </div>
                  <div className="text-right">
                    <p className="text-xs text-(--t-2)">
                      Authority {domain.avg_authority_score.toFixed(1)}
                    </p>
                    <p className="text-xs text-(--t-2)">
                      Sentiment {domain.avg_sentiment_score.toFixed(3)}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </GlassCard>

        <GlassCard className="space-y-4 p-5">
          <p className="text-[10px] font-black uppercase tracking-widest text-(--t-3)">
            Actionable Advice
          </p>
          {summary.actionable_advice.length === 0 ? (
            <p className="text-sm text-(--t-2)">No urgent actions detected for this period.</p>
          ) : (
            <div className="space-y-3">
              {summary.actionable_advice.slice(0, 4).map((advice, index) => (
                <div
                  key={`${advice.title}-${index}`}
                  className="rounded-xl border-0 bg-(--line-2) p-3"
                >
                  <p className="text-xs font-bold uppercase tracking-widest text-(--t-3)">
                    {advice.priority}
                  </p>
                  <p className="mt-1 text-sm font-semibold text-(--t-1)">{advice.title}</p>
                  <p className="mt-1 text-xs text-(--t-2)">{advice.message}</p>
                  {advice.mention_url ? (
                    <a
                      href={advice.mention_url}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-primary hover:text-(--purple)"
                    >
                      Open mention <ExternalLink className="h-3 w-3" />
                    </a>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </GlassCard>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <GlassCard className="space-y-4 p-5">
          <p className="text-[10px] font-black uppercase tracking-widest text-(--t-3)">
            30-Day Trend
          </p>
          {!trends || trends.points.length === 0 ? (
            <p className="text-sm text-(--t-2)">No trend data available.</p>
          ) : (
            <div className="space-y-2">
              {trends.points.slice(-7).map((point) => (
                <div
                  key={point.date}
                  className="flex items-center justify-between rounded-[14px] border-0 bg-[#EEF1F6] bg-(--line-2) px-3 py-2 text-xs text-(--t-2)"
                >
                  <span>{formatDate(point.date)}</span>
                  <span>
                    {point.off_page_aeo_score === null
                      ? "N/A"
                      : `${point.off_page_aeo_score.toFixed(2)}%`}
                  </span>
                  <span>{formatNumber(point.total_mentions)} mentions</span>
                </div>
              ))}
            </div>
          )}
        </GlassCard>

        <GlassCard className="space-y-4 p-5">
          <p className="text-[10px] font-black uppercase tracking-widest text-(--t-3)">
            Latest Mentions
          </p>
          {feed.length === 0 ? (
            <p className="text-sm text-(--t-2)">No mention feed rows yet.</p>
          ) : (
            <div className="space-y-3">
              {feed.slice(0, 6).map((mention) => (
                <div
                  key={mention.id}
                  className="rounded-xl border-0 bg-(--line-2) p-3"
                >
                  <p className="text-xs text-(--t-2)">
                    {mention.source_domain || mention.source_type} •{" "}
                    {formatDate(mention.published_at || mention.discovered_at)}
                  </p>
                  <p className="mt-1 text-sm font-semibold text-(--t-1)">
                    {mention.title || "Untitled mention"}
                  </p>
                  <p className="mt-1 line-clamp-2 text-xs text-(--t-2)">{mention.snippet}</p>
                  <div className="mt-2 flex items-center justify-between text-xs">
                    <span className="text-(--t-2)">Sentiment: {mention.sentiment_label}</span>
                    <span className="text-(--t-2)">
                      Authority: {mention.authority_score.toFixed(1)}
                    </span>
                  </div>
                  {mention.mention_url ? (
                    <a
                      href={mention.mention_url}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-primary hover:text-(--purple)"
                    >
                      Open mention <ExternalLink className="h-3 w-3" />
                    </a>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </GlassCard>
      </div>
    </ProjectMonitoringSection>
  );
}
