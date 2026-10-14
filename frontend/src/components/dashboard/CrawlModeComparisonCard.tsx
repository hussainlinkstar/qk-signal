"use client";

import React from "react";
import { Sparkles, Layers, Clock, CreditCard, BarChart3, Target, Lightbulb } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassComponents";
import Badge from "@/components/ui/Badge";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type CrawlMode = "bulk" | "smart";

export interface CrawlRecommendation {
  recommended: CrawlMode;
  reason: string;
}

/* ------------------------------------------------------------------ */
/*  Recommendation logic                                               */
/* ------------------------------------------------------------------ */

/**
 * Derive a crawl-mode recommendation from site size.
 *
 * Rules (from task spec):
 * - Site < 50 pages  → bulk (full coverage is cheap)
 * - Site > 500 pages + first audit → smart (quick overview)
 * - Repeat audit     → smart (ideal for tracking changes)
 * - Otherwise        → smart (balanced default)
 */
export function deriveCrawlRecommendation(
  totalSiteUrls: number | null,
  hasExistingCrawl: boolean
): CrawlRecommendation {
  if (totalSiteUrls !== null && totalSiteUrls < 50) {
    return {
      recommended: "bulk",
      reason:
        "Your site has fewer than 50 pages, a bulk crawl gives full coverage at a low scan cost.",
    };
  }

  if (hasExistingCrawl) {
    return {
      recommended: "smart",
      reason:
        "Smart Crawl is ideal for tracking changes since your last audit, it focuses on representative pages across every page type.",
    };
  }

  if (totalSiteUrls !== null && totalSiteUrls > 500) {
    return {
      recommended: "smart",
      reason:
        "Your site has 500+ pages, Smart Crawl gives a quick overview by sampling representative pages from each page type.",
    };
  }

  return {
    recommended: "smart",
    reason: "Smart Crawl offers efficient site-wide insights at a fraction of the scans and time.",
  };
}

/* ------------------------------------------------------------------ */
/*  Comparison rows                                                    */
/* ------------------------------------------------------------------ */

interface ComparisonRow {
  label: string;
  icon: React.ReactNode;
  smart: string;
  bulk: string;
}

const COMPARISON_ROWS: ComparisonRow[] = [
  {
    label: "Pages analyzed",
    icon: <BarChart3 className="h-3.5 w-3.5" />,
    smart: "15\u201350 representative",
    bulk: "All pages",
  },
  {
    label: "Time",
    icon: <Clock className="h-3.5 w-3.5" />,
    smart: "2\u20135 minutes",
    bulk: "10\u201360 minutes",
  },
  {
    label: "Scans",
    icon: <CreditCard className="h-3.5 w-3.5" />,
    smart: "1\u20132 scans",
    bulk: "1 scan per page",
  },
  {
    label: "Best for",
    icon: <Target className="h-3.5 w-3.5" />,
    smart: "Quick health check, trend monitoring",
    bulk: "Full site audit, pre-launch review",
  },
];

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

interface CrawlModeComparisonCardProps {
  recommendation?: CrawlRecommendation | null;
  activeMode: CrawlMode;
  onSelectMode: (mode: CrawlMode) => void;
}

export default function CrawlModeComparisonCard({
  recommendation,
  activeMode,
  onSelectMode,
}: CrawlModeComparisonCardProps) {
  return (
    <GlassCard className="space-y-4 border-(--line) bg-[color-mix(in_srgb,var(--panel)_70%,transparent)] p-5">
      <div className="flex items-center gap-2">
        <Lightbulb className="h-4 w-4 text-amber-400" />
        <h3 className="text-sm font-semibold text-(--t-1)">Smart Crawl vs Bulk Crawl</h3>
      </div>

      {/* Recommendation banner */}
      {recommendation ? (
        <div className="flex items-start gap-3 rounded border border-primary/20 bg-primary/5 px-4 py-3">
          <div className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/20 text-primary">
            {recommendation.recommended === "smart" ? (
              <Sparkles className="h-3 w-3" />
            ) : (
              <Layers className="h-3 w-3" />
            )}
          </div>
          <div className="min-w-0">
            <p className="text-xs font-semibold text-(--t-1)">
              Recommended:{" "}
              <span className="text-primary">
                {recommendation.recommended === "smart" ? "Smart Crawl" : "Bulk Crawl"}
              </span>
            </p>
            <p className="mt-0.5 text-xs text-(--t-2)">{recommendation.reason}</p>
          </div>
        </div>
      ) : null}

      {/* Comparison table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse" role="table">
          <thead>
            <tr className="border-b border-(--line) text-left text-xs uppercase tracking-wider text-(--t-2)">
              <th className="px-5 py-3 text-left font-(family-name:--mono) text-[10px] uppercase tracking-[0.06em] text-(--t-3) font-normal border-b border-b-(--line)">
                Feature
              </th>
              <th className="px-5 py-3 text-left font-(family-name:--mono) text-[10px] uppercase tracking-[0.06em] text-(--t-3) font-normal border-b border-b-(--line)">
                <button
                  type="button"
                  onClick={() => onSelectMode("smart")}
                  className={`flex items-center gap-1.5 transition ${
                    activeMode === "smart"
                      ? "font-bold text-primary"
                      : "text-(--t-2) hover:text-(--t-1)"
                  }`}
                  aria-label="Select Smart Crawl mode"
                >
                  <Sparkles className="h-3 w-3" />
                  Smart Crawl
                </button>
              </th>
              <th className="px-5 py-3 text-left font-(family-name:--mono) text-[10px] uppercase tracking-[0.06em] text-(--t-3) font-normal border-b border-b-(--line)">
                <button
                  type="button"
                  onClick={() => onSelectMode("bulk")}
                  className={`flex items-center gap-1.5 transition ${
                    activeMode === "bulk"
                      ? "font-bold text-primary"
                      : "text-(--t-2) hover:text-(--t-1)"
                  }`}
                  aria-label="Select Bulk Crawl mode"
                >
                  <Layers className="h-3 w-3" />
                  Bulk Crawl
                </button>
              </th>
            </tr>
          </thead>
          <tbody>
            {COMPARISON_ROWS.map((row) => (
              <tr
                key={row.label}
                className="border-b border-(--line) text-(--t-1) last:[&>td]:border-b-0"
              >
                <td className="px-5 py-[13px] text-[13px] border-b border-b-(--line-2)">
                  <span className="flex items-center gap-1.5 text-(--t-2)">
                    {row.icon}
                    {row.label}
                  </span>
                </td>
                <td
                  className={`px-5 py-[13px] text-[13px] border-b border-b-(--line-2) ${activeMode === "smart" ? "text-(--t-1)" : ""}`}
                >
                  {row.smart}
                </td>
                <td
                  className={`px-5 py-[13px] text-[13px] border-b border-b-(--line-2) ${activeMode === "bulk" ? "text-(--t-1)" : ""}`}
                >
                  {row.bulk}
                </td>
              </tr>
            ))}
            <tr className="border-b border-(--line) text-(--t-1) last:[&>td]:border-b-0">
              <td className="px-5 py-[13px] text-[13px] border-b border-b-(--line-2)">
                <span className="flex items-center gap-1.5 text-(--t-2)">
                  <BarChart3 className="h-3.5 w-3.5" />
                  Coverage
                </span>
              </td>
              <td className="px-5 py-[13px] text-[13px] border-b border-b-(--line-2)">
                <Badge color="info" size="sm">
                  Statistical sample
                </Badge>
              </td>
              <td className="px-5 py-[13px] text-[13px] border-b border-b-(--line-2)">
                <Badge color="success" size="sm">
                  100%
                </Badge>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </GlassCard>
  );
}
