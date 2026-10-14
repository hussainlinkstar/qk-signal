"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/auth/custom-auth";
import {
  Trophy,
  TrendingUp,
  TrendingDown,
  Minus,
  Search,
  CheckCircle2,
  XCircle,
  MessageSquareMore,
  Sparkles,
} from "lucide-react";
import {
  ProjectMonitoringWidgetCard,
  ProjectMonitoringWidgetEmptyState,
  ProjectMonitoringWidgetInlineError,
} from "@/components/dashboard/ProjectMonitoringSection";
import { SerpFeatureList, SerpFeatureSummary } from "@/components/dashboard/SerpFeatureBadge";

/* ------------------------------------------------------------------ */
/* Types                                                               */
/* ------------------------------------------------------------------ */

type PAA = {
  question: string;
  url: string;
  position: number;
};

type SERPSnapshotItem = {
  keyword: string;
  keyword_id: number;
  snapshot_date: string;
  owns_featured_snippet: boolean;
  featured_snippet_url?: string | null;
  paa_appearances: PAA[];
  organic_position: number | null;
  serp_features_present: string[];
  ai_overview_detected: boolean;
  ai_overview_cites_target: boolean;
  ai_overview_source_urls?: string[] | null;
};

type SERPTrackingSummary = {
  project_id: number;
  total_keywords: number;
  snippets_owned: number;
  snippets_gained: number;
  snippets_lost: number;
  paa_appearances_total: number;
  ai_overview_count: number;
  ai_overview_cited_count: number;
  latest_snapshots: SERPSnapshotItem[];
};

/* ------------------------------------------------------------------ */
/* Stat Card                                                           */
/* ------------------------------------------------------------------ */

function StatCard({
  label,
  value,
  icon: Icon,
  accent,
}: {
  label: string;
  value: string | number;
  icon: React.ElementType;
  accent: string;
}) {
  return (
    <div className="rounded-xl border border-(--line) bg-(--line-2) p-4 flex items-center gap-3 min-w-0">
      <div
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border bg-(--abg) border-(--abr)"
        style={{ "--abg": `${accent}20`, "--abr": `${accent}40` } as React.CSSProperties}
      >
        <Icon size={16} className="text-(--c)" style={{ "--c": accent } as React.CSSProperties} />
      </div>
      <div className="min-w-0">
        <p className="text-[10px] font-bold uppercase tracking-widest text-(--t-3)">{label}</p>
        <p className="text-lg font-bold text-(--t-1) tabular-nums mt-0.5">{value}</p>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Delta Badge                                                         */
/* ------------------------------------------------------------------ */

function DeltaBadge({ gained, lost }: { gained: number; lost: number }) {
  const net = gained - lost;
  if (net > 0) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 px-2.5 py-1 text-xs font-semibold text-emerald-400">
        <TrendingUp size={12} />+{net} net
      </span>
    );
  }
  if (net < 0) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/10 border border-rose-500/30 px-2.5 py-1 text-xs font-semibold text-rose-400">
        <TrendingDown size={12} />
        {net} net
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-(--line-2) border border-(--line) px-2.5 py-1 text-xs font-semibold text-(--t-2)">
      <Minus size={12} />
      No change
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Keyword Table                                                       */
/* ------------------------------------------------------------------ */

function KeywordTable({ snapshots }: { snapshots: SERPSnapshotItem[] }) {
  if (!snapshots.length) {
    return (
      <ProjectMonitoringWidgetEmptyState
        icon={Search}
        title="No keyword snapshots yet"
        description="Add target keywords and run the monitoring worker to start tracking Featured Snippets and PAA appearances."
      />
    );
  }

  return (
    <div className="overflow-x-auto -mx-1">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="border-b border-(--line)">
            <th className="pb-3 text-[10px] font-bold uppercase tracking-widest text-(--t-3) pl-2">
              Keyword
            </th>
            <th className="pb-3 text-[10px] font-bold uppercase tracking-widest text-(--t-3) text-center">
              Snippet
            </th>
            <th className="pb-3 text-[10px] font-bold uppercase tracking-widest text-(--t-3) text-center">
              PAA
            </th>
            <th className="pb-3 text-[10px] font-bold uppercase tracking-widest text-(--t-3) text-center">
              AI Overview
            </th>
            <th className="pb-3 text-[10px] font-bold uppercase tracking-widest text-(--t-3) text-center">
              Organic #
            </th>
            <th className="pb-3 text-[10px] font-bold uppercase tracking-widest text-(--t-3) text-center">
              SERP Features
            </th>
            <th className="pb-3 text-[10px] font-bold uppercase tracking-widest text-(--t-3) text-right pr-2">
              Last Check
            </th>
          </tr>
        </thead>
        <tbody>
          {snapshots.map((snap) => (
            <tr
              key={snap.keyword_id}
              className="border-b border-(--line) hover:bg-(--line-2) transition-colors"
            >
              <td className="py-3 pl-2">
                <span className="text-(--t-1) font-medium">{snap.keyword}</span>
              </td>
              <td className="py-3 text-center">
                {snap.owns_featured_snippet ? (
                  <span className="inline-flex items-center gap-1 text-emerald-400">
                    <CheckCircle2 size={14} />
                    <span className="font-semibold">Owned</span>
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-(--t-3)">
                    <XCircle size={14} />
                    <span>-</span>
                  </span>
                )}
              </td>
              <td className="py-3 text-center">
                {snap.paa_appearances.length > 0 ? (
                  <span className="inline-flex items-center gap-1 text-(--purple)">
                    <MessageSquareMore size={14} />
                    <span className="font-semibold">{snap.paa_appearances.length}</span>
                  </span>
                ) : (
                  <span className="text-(--t-3)">-</span>
                )}
              </td>
              <td className="py-3 text-center">
                {snap.ai_overview_detected ? (
                  snap.ai_overview_cites_target ? (
                    <span className="inline-flex items-center gap-1 text-emerald-400">
                      <Sparkles size={14} />
                      <span className="font-semibold">Cited</span>
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-amber-400">
                      <Sparkles size={14} />
                      <span className="font-semibold">Present</span>
                    </span>
                  )
                ) : (
                  <span className="text-(--t-3)">-</span>
                )}
              </td>
              <td className="py-3 text-center">
                {snap.organic_position ? (
                  <span
                    className={`font-bold tabular-nums ${
                      snap.organic_position <= 3
                        ? "text-emerald-400"
                        : snap.organic_position <= 10
                          ? "text-amber-400"
                          : "text-(--t-2)"
                    }`}
                  >
                    #{snap.organic_position}
                  </span>
                ) : (
                  <span className="text-(--t-3)">-</span>
                )}
              </td>
              <td className="py-3 text-center">
                <SerpFeatureList features={snap.serp_features_present} />
              </td>
              <td className="py-3 text-right pr-2">
                <span className="text-(--t-3) tabular-nums">{snap.snapshot_date}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Main Component                                                      */
/* ------------------------------------------------------------------ */

type Props = {
  projectId: number | string;
  className?: string;
};

export default function SnippetBattlePanel({ projectId, className = "" }: Props) {
  const { getToken } = useAuth();
  const [data, setData] = useState<SERPTrackingSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      const response = await fetch(`/api/v1/projects/${projectId}/monitoring/serp-tracking`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) throw new Error("Failed to load SERP tracking data");
      const payload: SERPTrackingSummary = await response.json();
      setData(payload);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "An unexpected error occurred");
    } finally {
      setLoading(false);
    }
  }, [getToken, projectId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  /* ------------------------------------------------------------------ */
  /* Render                                                              */
  /* ------------------------------------------------------------------ */

  if (loading) {
    return (
      <ProjectMonitoringWidgetCard
        icon={Trophy}
        title="Featured Snippets & PAA Battle"
        description="Track snippet ownership, PAA appearances, and keyword-level answer visibility."
        className={className}
        iconShellClassName="border-amber-500/30 bg-linear-to-br from-amber-500/20 to-orange-500/20"
        iconClassName="text-amber-400"
      >
        <div className="animate-pulse space-y-3">
          <div className="h-4 w-64 rounded bg-(--line-2)" />
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className="h-20 rounded-xl bg-(--line-2)" />
            ))}
          </div>
          <div className="h-48 w-full rounded-xl bg-(--line-2) mt-4" />
        </div>
      </ProjectMonitoringWidgetCard>
    );
  }

  if (error) {
    return (
      <ProjectMonitoringWidgetCard
        icon={Trophy}
        title="Featured Snippets & PAA Battle"
        description="Track snippet ownership, PAA appearances, and keyword-level answer visibility."
        className={className}
        iconShellClassName="border-amber-500/30 bg-linear-to-br from-amber-500/20 to-orange-500/20"
        iconClassName="text-amber-400"
      >
        <ProjectMonitoringWidgetInlineError message={error} />
      </ProjectMonitoringWidgetCard>
    );
  }

  return (
    <ProjectMonitoringWidgetCard
      icon={Trophy}
      title="Featured Snippets & PAA Battle"
      description={`${data?.total_keywords ?? 0} keywords tracked · 30-day delta`}
      className={className}
      iconShellClassName="border-amber-500/30 bg-linear-to-br from-amber-500/20 to-orange-500/20"
      iconClassName="text-amber-400"
      headerAside={
        data ? <DeltaBadge gained={data.snippets_gained} lost={data.snippets_lost} /> : null
      }
    >
      {/* Stat Cards row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-6">
        <StatCard
          label="Snippets Owned"
          value={data?.snippets_owned ?? 0}
          icon={Trophy}
          accent="#D97706" /* token: --warning */
        />
        <StatCard
          label="Gained (30d)"
          value={`+${data?.snippets_gained ?? 0}`}
          icon={TrendingUp}
          accent="#16A34A"
        />
        <StatCard
          label="Lost (30d)"
          value={`-${data?.snippets_lost ?? 0}`}
          icon={TrendingDown}
          accent="#EF4444" /* token: --danger */
        />
        <StatCard
          label="PAA Appearances"
          value={data?.paa_appearances_total ?? 0}
          icon={MessageSquareMore}
          accent="#6366F1" /* token: --primary */
        />
        <StatCard
          label="AI Overviews"
          value={data?.ai_overview_count ?? 0}
          icon={Sparkles}
          accent="#8B5CF6"
        />
        <StatCard
          label="AIO Cited"
          value={data?.ai_overview_cited_count ?? 0}
          icon={Sparkles}
          accent="#16A34A"
        />
      </div>

      {/* SERP Feature Distribution */}
      <div className="mb-6">
        <SerpFeatureSummary snapshots={data?.latest_snapshots ?? []} />
      </div>

      {/* Keyword Table */}
      <KeywordTable snapshots={data?.latest_snapshots ?? []} />
    </ProjectMonitoringWidgetCard>
  );
}
