"use client";

import React, { useMemo } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AlertCircle, LineChart as LineChartIcon, TrendingUp } from "lucide-react";

import Card from "@/components/ui/Card";
import {
  CHART_AXIS_STROKE,
  CHART_AXIS_TICK,
  CHART_GRID_STROKE,
  CHART_LEGEND_TEXT_CLASS,
  CHART_TOOLTIP_LABEL_CLASS,
  CHART_TOOLTIP_VALUE_CLASS,
  getChartColor,
} from "@/components/ui/chartTokens";
import {
  CARD_CONTAINER_PRESETS,
  CARD_LABEL_CLASS,
  DASHBOARD_CARD_CLASS,
} from "@/components/ui/cardStyleTokens";
import { TYPO } from "@/components/ui/typographyTokens";
import type { VisibilityProvider, VisibilityTrendResponse } from "@/types/monitoring";
import {
  VISIBILITY_PROVIDER_LABELS,
  measuredVisibilityProviders,
} from "@/components/dashboard/visibilityUtils";

type VisibilityTrendChartProps = {
  trends: VisibilityTrendResponse | null;
  /**
   * The engines this project's plan measures (SIGV2-1216). The trend payload
   * is derived from recorded cells, so an engine the plan stopped measuring
   * still has points in it. Omitted means "no roster in scope" and leaves the
   * series as the backend sent them.
   */
  allowedProviders?: readonly string[] | null;
  loading?: boolean;
  error?: string | null;
};

// One colour per backend provider key, plus the `overall` series. Typed as
// Record<VisibilityProvider | "overall", string> rather than Record<string,
// string> so a provider added to the contract cannot be left without a colour
// (SIGV2-1163: `meta` was keyed `meta_ai` here, a value the backend never
// sends, so a real `meta` series would have drawn with no colour at all).
// Exported for `src/types/monitoring.providerContract.test.ts`.
export const PROVIDER_COLORS: Record<VisibilityProvider | "overall", string> = {
  overall: getChartColor(0),
  google: getChartColor(0),
  openai: getChartColor(1),
  anthropic: getChartColor(3),
  bing: getChartColor(5),
  perplexity: getChartColor(4),
  xai: getChartColor(6),
  deepseek: getChartColor(7),
  meta: getChartColor(2),
};

function TrendTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) {
    return null;
  }

  return (
    <div className="rounded-2xl border border-(--border) bg-(--chart-tooltip-bg) px-4 py-3">
      <p className={CHART_TOOLTIP_LABEL_CLASS}>{label}</p>
      <div className="mt-2 space-y-2">
        {payload.map((entry) => (
          <div key={entry.name} className="flex items-center justify-between gap-6 text-xs">
            <div className="flex items-center gap-2 text-(--text-soft)">
              <span
                className="h-2.5 w-2.5 rounded-full bg-(--c)"
                style={{ "--c": entry.color } as React.CSSProperties}
              />
              <span>
                {entry.name === "overall"
                  ? "Overall"
                  : VISIBILITY_PROVIDER_LABELS[
                      entry.name as keyof typeof VISIBILITY_PROVIDER_LABELS
                    ]}
              </span>
            </div>
            <span className={CHART_TOOLTIP_VALUE_CLASS}>{Math.round(entry.value)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function VisibilityTrendChart({
  trends,
  allowedProviders = null,
  loading = false,
  error = null,
}: VisibilityTrendChartProps) {
  // SIGV2-1215: a withdrawn engine gets no line and no legend entry. The
  // overall series is the backend's own blended score and is unaffected.
  //
  // SIGV2-1216: nor does an engine the plan has stopped measuring, on any
  // day, including the days it was still being measured. That is the
  // deliberate choice over cutting the line where the engine's cells stop: a
  // cut leaves a step, and a step in a score chart reads as a drop in the
  // customer's performance when it is only a change in what is measured. The
  // backend re-reads history through the current roster for the same reason,
  // so the whole line moves level once and no point sits on a different set
  // of engines from the point beside it. Nothing needs saying on the chart,
  // because there is nothing visible to explain.
  const providers = useMemo(
    () => measuredVisibilityProviders(trends?.providers, allowedProviders),
    [allowedProviders, trends?.providers]
  );

  const chartData = useMemo(() => {
    if (!trends) {
      return [];
    }

    return trends.points.map((point) => {
      const row: Record<string, number | string | null> = {
        date: point.date,
        overall: point.visibility_score,
      };
      providers.forEach((provider) => {
        row[provider] = point.providers[provider] ?? null;
      });
      return row;
    });
  }, [providers, trends]);

  if (loading) {
    return (
      <Card className={`${CARD_CONTAINER_PRESETS.primary} ${DASHBOARD_CARD_CLASS}`}>
        <div className="animate-pulse space-y-4">
          <div className="h-3 w-32 rounded bg-(--surface-subtle)" />
          <div className="h-7 w-52 rounded bg-(--surface-subtle)" />
          <div className="h-80 rounded-2xl bg-(--surface-subtle)" />
        </div>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className={`${CARD_CONTAINER_PRESETS.primary} ${DASHBOARD_CARD_CLASS}`}>
        <div className="flex items-center gap-3 text-warning">
          <AlertCircle className="h-5 w-5" />
          <div>
            <p className={CARD_LABEL_CLASS}>AI Visibility</p>
            <h2 className={TYPO.sectionTitle}>Visibility Trend</h2>
            <p className="mt-2 text-sm text-(--text-muted)">{error}</p>
          </div>
        </div>
      </Card>
    );
  }

  if (!trends || chartData.length === 0) {
    return (
      <Card className={`${CARD_CONTAINER_PRESETS.primary} ${DASHBOARD_CARD_CLASS}`}>
        <p className={CARD_LABEL_CLASS}>AI Visibility</p>
        <h2 className={TYPO.sectionTitle}>Visibility Trend</h2>
        <p className="text-sm text-(--text-muted)">
          Trend history will appear after the first completed visibility runs.
        </p>
      </Card>
    );
  }

  return (
    <Card className={`${CARD_CONTAINER_PRESETS.primary} ${DASHBOARD_CARD_CLASS}`}>
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <p className={CARD_LABEL_CLASS}>AI Visibility</p>
          <h2 className={TYPO.sectionTitle}>Visibility Trend</h2>
        </div>
        <div className="inline-flex items-center gap-2 rounded-full border border-(--border) bg-(--surface) px-3 py-1.5 text-xs font-semibold text-(--text-soft)">
          <TrendingUp className="h-4 w-4 text-primary" />
          Last {trends.days} days
        </div>
      </div>

      <div className="h-80 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 12, right: 12, left: 0, bottom: 4 }}>
            <CartesianGrid stroke={CHART_GRID_STROKE} vertical={false} />
            <XAxis
              dataKey="date"
              stroke={CHART_AXIS_STROKE}
              tick={CHART_AXIS_TICK}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              domain={[0, 100]}
              stroke={CHART_AXIS_STROKE}
              tick={CHART_AXIS_TICK}
              tickFormatter={(value) => `${value}%`}
              tickLine={false}
              axisLine={false}
              width={44}
            />
            <Tooltip content={<TrendTooltip />} />
            <Legend
              itemSorter={null}
              formatter={(value: string) => (
                <span className={CHART_LEGEND_TEXT_CLASS}>
                  {value === "overall"
                    ? "Overall"
                    : VISIBILITY_PROVIDER_LABELS[value as keyof typeof VISIBILITY_PROVIDER_LABELS]}
                </span>
              )}
            />
            <Line
              type="monotone"
              dataKey="overall"
              stroke={PROVIDER_COLORS.overall}
              strokeWidth={3}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
              connectNulls
            />
            {providers.map((provider) => (
              <Line
                key={provider}
                type="monotone"
                dataKey={provider}
                stroke={PROVIDER_COLORS[provider] ?? "var(--chart-6)"}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="inline-flex items-center gap-2 text-xs text-(--text-soft)">
        <LineChartIcon className="h-4 w-4" />
        Overall score is based on completed provider checks for each day.
      </div>
    </Card>
  );
}
