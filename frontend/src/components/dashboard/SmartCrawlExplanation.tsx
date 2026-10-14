"use client";

import React from "react";
import { Sparkles, AlertTriangle, CheckCircle2, Info, BarChart3 } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassComponents";
import Badge from "@/components/ui/Badge";

/* ------------------------------------------------------------------ */
/*  Types (mirrors backend smart_crawl block)                          */
/* ------------------------------------------------------------------ */

export interface SmartCrawlExtrapolatedIssue {
  page_type: string;
  label: string;
  sampled: number;
  estimated_total: number;
  avg_score: number;
  projected_affected_pages: number;
  confidence: "high" | "medium";
  insight: string;
}

export interface SmartCrawlReportData {
  mode: string;
  total_site_urls: number;
  sampled_urls: number;
  coverage_ratio: number;
  page_type_distribution: Record<string, number>;
  extrapolated_issues: SmartCrawlExtrapolatedIssue[];
  extrapolation_note: string;
}

export interface PageTypeBreakdownEntry {
  count: number;
  avg_geo: number | null;
  avg_seo: number | null;
  avg_aeo: number | null;
  avg_overall: number | null;
}

/* ------------------------------------------------------------------ */
/*  Helper: score color                                                */
/* ------------------------------------------------------------------ */

function scoreColor(score: number | null): string {
  if (score === null) return "text-(--t-3)";
  if (score >= 80) return "text-emerald-400";
  if (score >= 60) return "text-amber-400";
  return "text-rose-400";
}

function confidenceBadgeColor(confidence: string): "success" | "warning" {
  return confidence === "high" ? "success" : "warning";
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

interface SmartCrawlExplanationProps {
  smartCrawl: SmartCrawlReportData;
  pageTypeBreakdown?: Record<string, PageTypeBreakdownEntry> | null;
}

export default function SmartCrawlExplanation({
  smartCrawl,
  pageTypeBreakdown,
}: SmartCrawlExplanationProps) {
  const coveragePct = Math.round(smartCrawl.coverage_ratio * 100);
  const typeCount = Object.keys(smartCrawl.page_type_distribution).length;

  /* Page-type diversity, how many types did we actually sample? */
  const sampledTypes = pageTypeBreakdown ? Object.keys(pageTypeBreakdown).length : 0;
  const diversityPct = typeCount > 0 ? Math.round((sampledTypes / typeCount) * 100) : 0;

  return (
    <GlassCard className="space-y-4 border-(--line) bg-[color-mix(in_srgb,var(--panel)_70%,transparent)] p-5">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-semibold text-(--t-1)">Smart Crawl Analysis</h3>
      </div>

      {/* Coverage summary */}
      <div className="grid gap-3 sm:grid-cols-3">
        <SummaryStat
          label="Pages sampled"
          value={`${smartCrawl.sampled_urls} / ${smartCrawl.total_site_urls}`}
          detail={`${coveragePct}% of site`}
        />
        <SummaryStat
          label="Page types covered"
          value={`${sampledTypes} / ${typeCount}`}
          detail={`${diversityPct}% type diversity`}
        />
        <SummaryStat
          label="Confidence"
          value={diversityPct >= 80 ? "High" : diversityPct >= 50 ? "Medium" : "Low"}
          detail={
            diversityPct >= 80
              ? "Broad coverage across page types"
              : "Some page types not represented"
          }
        />
      </div>

      {/* Page type breakdown table */}
      {pageTypeBreakdown && Object.keys(pageTypeBreakdown).length > 0 ? (
        <div>
          <div className="mb-2 flex items-center gap-1.5">
            <BarChart3 className="h-3.5 w-3.5 text-(--t-2)" />
            <p className="text-xs font-bold uppercase tracking-wider text-(--t-2)">
              Scores by Page Type
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse" role="table">
              <thead>
                <tr className="border-b border-(--line) text-left text-xs uppercase tracking-wider text-(--t-2)">
                  <th className="px-5 py-3 text-left font-(family-name:--mono) text-[10px] uppercase tracking-[0.06em] text-(--t-3) font-normal border-b border-b-(--line)">
                    Page Type
                  </th>
                  <th className="px-5 py-3 text-left font-(family-name:--mono) text-[10px] uppercase tracking-[0.06em] text-(--t-3) font-normal border-b border-b-(--line)">
                    Sampled
                  </th>
                  <th className="px-5 py-3 text-left font-(family-name:--mono) text-[10px] uppercase tracking-[0.06em] text-(--t-3) font-normal border-b border-b-(--line)">
                    Total
                  </th>
                  <th className="px-5 py-3 text-left font-(family-name:--mono) text-[10px] uppercase tracking-[0.06em] text-(--t-3) font-normal border-b border-b-(--line)">
                    Overall
                  </th>
                  <th className="px-5 py-3 text-left font-(family-name:--mono) text-[10px] uppercase tracking-[0.06em] text-(--t-3) font-normal border-b border-b-(--line)">
                    SEO
                  </th>
                  <th className="px-5 py-3 text-left font-(family-name:--mono) text-[10px] uppercase tracking-[0.06em] text-(--t-3) font-normal border-b border-b-(--line)">
                    AI visibility
                  </th>
                  <th className="px-5 py-3 text-left font-(family-name:--mono) text-[10px] uppercase tracking-[0.06em] text-(--t-3) font-normal border-b border-b-(--line)">
                    AI answers
                  </th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(pageTypeBreakdown)
                  .sort(([, a], [, b]) => (a.avg_overall ?? 0) - (b.avg_overall ?? 0))
                  .map(([ptype, data]) => {
                    const totalInType = smartCrawl.page_type_distribution[ptype] ?? data.count;
                    return (
                      <tr
                        key={ptype}
                        className="border-b border-(--line) text-(--t-1) last:[&>td]:border-b-0"
                      >
                        <td className="px-5 py-[13px] text-[13px] border-b border-b-(--line-2) capitalize">
                          {ptype.replace(/_/g, " ")}
                        </td>
                        <td className="px-5 py-[13px] text-[13px] border-b border-b-(--line-2) text-center">
                          {data.count}
                        </td>
                        <td className="px-5 py-[13px] text-[13px] border-b border-b-(--line-2) text-center text-(--t-2)">
                          {totalInType}
                        </td>
                        <td
                          className={`px-5 py-[13px] text-[13px] border-b border-b-(--line-2) text-center font-medium ${scoreColor(data.avg_overall)}`}
                        >
                          {data.avg_overall !== null ? Math.round(data.avg_overall) : "\u2014"}
                        </td>
                        <td
                          className={`px-5 py-[13px] text-[13px] border-b border-b-(--line-2) text-center ${scoreColor(data.avg_seo)}`}
                        >
                          {data.avg_seo !== null ? Math.round(data.avg_seo) : "\u2014"}
                        </td>
                        <td
                          className={`px-5 py-[13px] text-[13px] border-b border-b-(--line-2) text-center ${scoreColor(data.avg_geo)}`}
                        >
                          {data.avg_geo !== null ? Math.round(data.avg_geo) : "\u2014"}
                        </td>
                        <td
                          className={`px-5 py-[13px] text-[13px] border-b border-b-(--line-2) text-center ${scoreColor(data.avg_aeo)}`}
                        >
                          {data.avg_aeo !== null ? Math.round(data.avg_aeo) : "\u2014"}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {/* Extrapolated issues */}
      {smartCrawl.extrapolated_issues.length > 0 ? (
        <div className="space-y-2">
          <div className="flex items-center gap-1.5">
            <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
            <p className="text-xs font-bold uppercase tracking-wider text-(--t-2)">
              Projected Site-wide Issues
            </p>
          </div>
          <div className="space-y-2">
            {smartCrawl.extrapolated_issues.map((issue) => (
              <div
                key={issue.page_type}
                className="flex items-start gap-3 rounded border border-(--line) bg-[color-mix(in_srgb,var(--panel)_40%,transparent)] px-3 py-2.5"
              >
                <div className="mt-0.5 shrink-0">
                  <Badge color={confidenceBadgeColor(issue.confidence)} size="sm">
                    {issue.confidence}
                  </Badge>
                </div>
                <div className="min-w-0">
                  <p className="text-sm text-(--t-1)">{issue.insight}</p>
                  <p className="mt-1 text-xs text-(--t-3)">
                    {issue.sampled} sampled &rarr; {issue.estimated_total} estimated total
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-2 rounded border border-emerald-500/20 bg-emerald-500/5 px-4 py-3">
          <CheckCircle2 className="h-4 w-4 text-emerald-400" />
          <p className="text-sm text-emerald-300">
            No critical issues projected across page types.
          </p>
        </div>
      )}

      {/* Extrapolation note */}
      <div className="flex items-start gap-2 text-xs text-(--t-3)">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <p>{smartCrawl.extrapolation_note}</p>
      </div>
    </GlassCard>
  );
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                     */
/* ------------------------------------------------------------------ */

function SummaryStat({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="rounded border border-(--line) bg-[color-mix(in_srgb,var(--panel)_40%,transparent)] px-3 py-2.5">
      <p className="text-[10px] font-bold uppercase tracking-wider text-(--t-3)">{label}</p>
      <p className="mt-1 text-lg font-bold text-(--t-1)">{value}</p>
      <p className="text-xs text-(--t-2)">{detail}</p>
    </div>
  );
}
