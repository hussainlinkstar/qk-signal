"use client";

import React, { useCallback, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { motion, useReducedMotion } from "motion/react";
import Card from "@/components/ui/Card";
import { useJiraExportTracker } from "@/hooks/useJiraExportTracker";
import type { AiStrategistViewModel, PriorityAction } from "@/types/aiStrategist";
import {
  calculateDelta,
  filterActionsByCategory,
  getPriorityScore,
  normalizeActionCategory,
  sortPriorityActions,
  type PriorityCategoryFilter,
} from "@/utils/seoCalculations";

type PriorityActionsTableProps = {
  latest?: Pick<AiStrategistViewModel, "priorityActions"> | null;
  siteUrl?: string | null;
  latestSeoScore?: number | null;
  previousSeoScore?: number | null;
  isLoading?: boolean;
  error?: string | null;
  isEmpty?: boolean;
  onRetry?: (() => void) | null;
  projectId?: string | number | null;
};

const FALLBACK_LABEL = "-";

const impactToneMap: Record<string, string> = {
  high: "border-red-400/40 bg-red-500/15 text-red-200",
  medium: "border-amber-400/40 bg-amber-500/15 text-amber-200",
  low: "border-[color-mix(in_srgb,var(--purple)_40%,transparent)] bg-cyan-500/15 text-(--purple)",
};

const effortToneMap: Record<string, string> = {
  high: "border-violet-400/30 bg-violet-500/15 text-violet-200",
  medium: "border-slate-400/30 bg-(--line-2) text-(--t-1)",
  low: "border-(--line) bg-slate-700/25 text-(--t-1)",
};

const categoryLabelMap: Record<PriorityCategoryFilter, string> = {
  all: "All",
  technical: "Technical",
  content: "Content",
  backlinks: "Backlinks",
};

const trendToneMap = {
  up: "text-emerald-300",
  down: "text-rose-300",
  flat: "text-(--t-2)",
} as const;

const toBadgeTone = (value: unknown, palette: Record<string, string>): string =>
  palette[String(value).toLowerCase()] ?? palette.medium;

const formatCategory = (value: string): string =>
  value
    .split("_")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");

const formatEta = (value: number | null | undefined): string => {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return FALLBACK_LABEL;
  }

  return `${value}d`;
};

const normalizeAction = (action: PriorityAction, index: number) => ({
  id: action.id || `priority-action-${index + 1}`,
  priority: Number.isFinite(Number(action.priority)) ? Number(action.priority) : null,
  title: action.title?.trim() || "Untitled action",
  description: action.description?.trim() || FALLBACK_LABEL,
  category: action.category ? formatCategory(action.category) : FALLBACK_LABEL,
  normalizedCategory: normalizeActionCategory(action.category),
  impact: action.impact || "medium",
  effort: action.effort || "medium",
  eta: formatEta(action.eta_days),
  owner: action.owner?.trim() || FALLBACK_LABEL,
  score: getPriorityScore(action.impact, action.effort),
});

export default function PriorityActionsTable({
  latest,
  latestSeoScore,
  previousSeoScore,
  isLoading = false,
  error = null,
  isEmpty = false,
  onRetry = null,
  projectId: propProjectId,
}: PriorityActionsTableProps) {
  const params = useParams<{ projectId: string }>();
  const projectId = propProjectId || params?.projectId || "";
  const shouldReduceMotion = useReducedMotion();
  const [activeFilter, setActiveFilter] = useState<PriorityCategoryFilter>("all");
  const { getTrackedExport } = useJiraExportTracker(projectId);

  const sortedActions = useMemo(
    () => sortPriorityActions(latest?.priorityActions ?? []),
    [latest?.priorityActions]
  );

  const rows = useMemo(
    () => filterActionsByCategory(sortedActions, activeFilter).map(normalizeAction),
    [activeFilter, sortedActions]
  );
  const handleCategoryChange = useCallback((category: PriorityCategoryFilter) => {
    setActiveFilter(category);
  }, []);

  const delta = calculateDelta(latestSeoScore, previousSeoScore);

  return (
    <motion.div
      initial={shouldReduceMotion ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={shouldReduceMotion ? { duration: 0 } : { duration: 0.32, ease: "easeOut" }}
    >
      <Card className="space-y-4 p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl font-bold tracking-tight text-(--t-1)">Priority SEO actions</h2>
          {delta.hasEnoughData ? (
            <p className={`text-sm font-medium ${trendToneMap[delta.trend]}`}>
              SEO trend vs previous audit: {delta.trendSymbol} {delta.percentage}%
            </p>
          ) : (
            <p className="text-sm text-(--t-2)">
              Trend unavailable: at least 2 comparable audits are required.
            </p>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          {(Object.keys(categoryLabelMap) as PriorityCategoryFilter[]).map((category) => (
            <button
              key={category}
              type="button"
              onClick={() => handleCategoryChange(category)}
              aria-label={`Filter actions by ${categoryLabelMap[category]} category`}
              className={`rounded-full border px-3 py-1 text-xs font-semibold transition focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-cyan-300/60 ${
                activeFilter === category
                  ? "border-cyan-300/60 bg-cyan-500/15 text-(--purple)"
                  : "border-(--line) bg-(--line-2) text-(--t-2) hover:border-(--line) hover:bg-(--line-2)"
              }`}
            >
              {categoryLabelMap[category]}
            </button>
          ))}
        </div>

        {isLoading ? (
          <div className="space-y-3" aria-live="polite" aria-busy="true">
            <div className="h-4 w-36 animate-pulse rounded bg-(--line-2)" />
            <div className="h-40 w-full animate-pulse rounded bg-(--line-2)" />
          </div>
        ) : error ? (
          <div className="space-y-3 rounded-lg border-0 bg-red-500/5 p-4 text-sm text-red-200">
            <p>{error}</p>
            {onRetry ? (
              <button
                type="button"
                onClick={onRetry}
                aria-label="Retry loading priority actions"
                className="inline-flex rounded-md border border-red-200/30 px-3 py-1.5 text-xs font-semibold text-red-100 hover:bg-red-500/10 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-red-200/60"
              >
                Retry
              </button>
            ) : null}
          </div>
        ) : isEmpty || sortedActions.length === 0 ? (
          <div className="rounded-xl border-0 bg-amber-500/10 p-4 text-sm font-medium text-amber-200 shadow-inner">
            No priority actions are available for this audit.
          </div>
        ) : rows.length === 0 ? (
          <div className="rounded-xl border-0 bg-amber-500/10 p-4 text-sm font-medium text-amber-200 shadow-inner">
            No actions are available in the selected category.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm" aria-label="Priority SEO actions table">
              <thead>
                <tr className="border-b border-(--line) text-thoth-brass">
                  <th className="px-3 py-2">Priority score</th>
                  <th className="px-3 py-2">Action</th>
                  <th className="px-3 py-2">Category</th>
                  <th className="px-3 py-2">Impact</th>
                  <th className="px-3 py-2">Effort</th>
                  <th className="px-3 py-2">ETA</th>
                  <th className="px-3 py-2">Owner</th>
                  <th className="px-3 py-2">AI</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((action) => {
                  const trackedExport = getTrackedExport(`priority:${action.title}`);
                  return (
                    <tr
                      key={action.id}
                      className="border-b border-(--line) text-(--t-1) transition-colors hover:bg-(--line-2) last:border-none"
                    >
                      <td className="px-3 py-2 font-semibold text-(--t-1)">{action.score}</td>
                      <td className="px-3 py-2">
                        <p className="font-semibold text-(--t-1)">{action.title}</p>
                        <p className="text-xs text-(--t-2)">{action.description}</p>
                      </td>
                      <td className="px-3 py-2">{action.category}</td>
                      <td className="px-3 py-2">
                        <span
                          className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-medium capitalize ${toBadgeTone(action.impact, impactToneMap)}`}
                        >
                          {action.impact}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-medium capitalize ${toBadgeTone(action.effort, effortToneMap)}`}
                        >
                          {action.effort}
                        </span>
                      </td>
                      <td className="px-3 py-2">{action.eta}</td>
                      <td className="px-3 py-2 text-(--t-2)">{action.owner}</td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-3">
                          {trackedExport ? (
                            <a
                              href={trackedExport.issueUrl}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-2 rounded-full border border-emerald-400/20 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-widest text-emerald-200 hover:text-(--t-1)"
                            >
                              {trackedExport.issueKey}
                            </a>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </motion.div>
  );
}
