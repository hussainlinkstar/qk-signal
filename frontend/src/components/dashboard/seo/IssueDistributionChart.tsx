"use client";

import React from "react";
import { motion, useReducedMotion } from "motion/react";
import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  type TooltipContentProps,
} from "recharts";
import Card from "@/components/ui/Card";
import {
  CHART_TOOLTIP_LABEL_CLASS,
  CHART_TOOLTIP_VALUE_CLASS,
  getChartColor,
} from "@/components/ui/chartTokens";
import type { AiStrategistViewModel } from "@/types/aiStrategist";

type IssueDistributionChartProps = {
  latest?: Pick<AiStrategistViewModel, "issueCategories"> | null;
  isLoading?: boolean;
  error?: string | null;
  isEmpty?: boolean;
  onRetry?: (() => void) | null;
};

type ChartDatum = {
  name: string;
  value: number;
  color: string;
};

const COLORS = [
  getChartColor(0),
  getChartColor(2),
  getChartColor(1),
  getChartColor(3),
  getChartColor(4),
  getChartColor(5),
];

function ChartTooltip({ active, payload }: Partial<TooltipContentProps<number, string>>) {
  if (!active || !payload?.length) {
    return null;
  }

  const point = payload[0]?.payload as ChartDatum | undefined;
  if (!point) {
    return null;
  }

  return (
    <div className="rounded-2xl border border-(--border) bg-(--chart-tooltip-bg) px-4 py-3">
      <p className={CHART_TOOLTIP_VALUE_CLASS}>{point.name}</p>
      <p
        className={`${CHART_TOOLTIP_LABEL_CLASS} mt-1 text-(--c)`}
        style={{ "--c": point.color } as React.CSSProperties}
      >
        {point.value} issues
      </p>
    </div>
  );
}

export default function IssueDistributionChart({
  latest,
  isLoading = false,
  error = null,
  isEmpty = false,
  onRetry = null,
}: IssueDistributionChartProps) {
  const shouldReduceMotion = useReducedMotion();
  const data = React.useMemo(() => {
    const issueCategories = latest?.issueCategories ?? [];

    return issueCategories
      .filter((category) => category.count > 0)
      .map((category, index) => ({
        name: category.label,
        value: category.count,
        color: COLORS[index % COLORS.length],
      }));
  }, [latest?.issueCategories]);

  const totalIssues = React.useMemo(
    () => data.reduce((acc, category) => acc + category.value, 0),
    [data]
  );

  return (
    <motion.div
      initial={shouldReduceMotion ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={shouldReduceMotion ? { duration: 0 } : { duration: 0.3, ease: "easeOut" }}
    >
      <Card className="space-y-4 p-6">
        <div>
          <h3 className="text-lg font-semibold text-(--foreground)">Issue distribution</h3>
          <p className="text-sm text-(--text-muted)">
            How SEO issues are split across major categories.
          </p>
        </div>

        {isLoading ? (
          <div className="space-y-4" aria-live="polite" aria-busy="true">
            <div className="h-4 w-44 animate-pulse rounded bg-(--surface-subtle)" />
            <div className="h-64 w-full animate-pulse rounded-2xl bg-(--surface-subtle)" />
          </div>
        ) : error ? (
          <div className="space-y-3 rounded-lg border border-danger/20 bg-danger/10 p-4 text-sm text-danger">
            <p>{error}</p>
            {onRetry ? (
              <button
                type="button"
                onClick={onRetry}
                aria-label="Retry loading issue distribution chart"
                className="inline-flex rounded-md border border-danger/20 px-3 py-1.5 text-xs font-semibold text-danger hover:bg-danger/10 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--ring)"
              >
                Retry
              </button>
            ) : null}
          </div>
        ) : isEmpty || data.length === 0 ? (
          <div className="rounded-xl border border-warning/20 bg-warning/10 p-4 text-sm font-medium text-warning shadow-inner">
            No issue categories with positive values are available for this audit.
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(220px,280px)] lg:items-center">
            <div className="h-72 w-full" role="img" aria-label="Issue distribution pie chart">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={data}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={70}
                    outerRadius={100}
                    paddingAngle={2}
                  >
                    {data.map((entry) => (
                      <Cell key={entry.name} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip cursor={false} content={<ChartTooltip />} />
                </PieChart>
              </ResponsiveContainer>
            </div>

            <ul className="space-y-2 text-sm" aria-label="Issue categories legend">
              {data.map((entry) => {
                const percentage = totalIssues > 0 ? (entry.value / totalIssues) * 100 : 0;

                return (
                  <li
                    key={`legend-${entry.name}`}
                    className="flex items-center justify-between gap-3 rounded-xl border border-(--border) bg-(--surface-subtle) px-4 py-3 transition-colors hover:bg-(--surface)"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <span
                        className="h-2.5 w-2.5 shrink-0 rounded-full bg-(--c)"
                        style={{ "--c": entry.color } as React.CSSProperties}
                        aria-hidden="true"
                      />
                      <span className="truncate text-(--foreground)">{entry.name}</span>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-(--text-soft)">
                      <span>{entry.value}</span>
                      <span className="text-(--text-muted)">•</span>
                      <span>{percentage.toFixed(1)}%</span>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </Card>
    </motion.div>
  );
}
