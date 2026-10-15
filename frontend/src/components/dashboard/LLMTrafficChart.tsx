"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { useAuth } from "@/components/auth/custom-auth";
import { TrendingUp, Bot, Layers } from "lucide-react";
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
  ProjectMonitoringWidgetCard,
  ProjectMonitoringWidgetEmptyState,
  ProjectMonitoringWidgetInlineError,
} from "@/components/dashboard/ProjectMonitoringSection";

/* ------------------------------------------------------------------ */
/* Types                                                               */
/* ------------------------------------------------------------------ */

type LLMTrafficDataPoint = {
  date: string;
  source: string;
  sessions: number;
  users?: number | null;
  page_views?: number | null;
};

type LLMTrafficResponse = {
  project_id: number;
  start_date: string;
  end_date: string;
  data: LLMTrafficDataPoint[];
  total_sessions: number;
  sources: string[];
};

type ChartRow = {
  date: string;
  [source: string]: number | string;
};

/* ------------------------------------------------------------------ */
/* Constants                                                           */
/* ------------------------------------------------------------------ */

const SOURCE_COLORS: Record<string, string> = {
  // Tier 1
  "chatgpt.com": getChartColor(0),
  "gemini.google.com": getChartColor(1),
  "copilot.microsoft.com": getChartColor(2),
  "claude.ai": getChartColor(3),
  "perplexity.ai": getChartColor(4),
  // Tier 2
  "deepseek.com": getChartColor(5),
  "chat.deepseek.com": getChartColor(5),
  "grok.com": getChartColor(6),
  "meta.ai": getChartColor(7),
  // Tier 3
  "chat.mistral.ai": getChartColor(8),
  "you.com": getChartColor(9),
  "poe.com": getChartColor(10),
  "phind.com": getChartColor(11),
  "search.brave.com": getChartColor(12),
  // Mobile
  "android-app://com.openai.chatgpt": getChartColor(0),
  "android-app://com.google.android.apps.bard": getChartColor(1),
};

const SOURCE_LABELS: Record<string, string> = {
  "chatgpt.com": "ChatGPT",
  "gemini.google.com": "Google Gemini",
  "copilot.microsoft.com": "Microsoft Copilot",
  "claude.ai": "Claude",
  "perplexity.ai": "Perplexity",
  "deepseek.com": "DeepSeek",
  "chat.deepseek.com": "DeepSeek Chat",
  "grok.com": "Grok",
  "meta.ai": "Meta AI",
  "chat.mistral.ai": "Mistral",
  "you.com": "You.com",
  "poe.com": "Poe",
  "phind.com": "Phind",
  "search.brave.com": "Brave Search",
  "android-app://com.openai.chatgpt": "ChatGPT (Android)",
  "android-app://com.google.android.apps.bard": "Gemini (Android)",
};

/* Platform family grouping, merges web + mobile variants */
const PLATFORM_FAMILIES: Record<string, string> = {
  "chatgpt.com": "OpenAI",
  "android-app://com.openai.chatgpt": "OpenAI",
  "gemini.google.com": "Google",
  "android-app://com.google.android.apps.bard": "Google",
  "copilot.microsoft.com": "Microsoft",
  "claude.ai": "Anthropic",
  "perplexity.ai": "Perplexity",
  "deepseek.com": "DeepSeek",
  "chat.deepseek.com": "DeepSeek",
  "grok.com": "xAI",
  "meta.ai": "Meta",
  "chat.mistral.ai": "Mistral",
  "you.com": "You.com",
  "poe.com": "Poe",
  "phind.com": "Phind",
  "search.brave.com": "Brave",
};

const FAMILY_COLORS: Record<string, string> = {
  OpenAI: getChartColor(0),
  Google: getChartColor(1),
  Microsoft: getChartColor(2),
  Anthropic: getChartColor(3),
  Perplexity: getChartColor(4),
  DeepSeek: getChartColor(5),
  xAI: getChartColor(6),
  Meta: getChartColor(7),
  Mistral: getChartColor(8),
  "You.com": getChartColor(9),
  Poe: getChartColor(10),
  Phind: getChartColor(11),
  Brave: getChartColor(12),
};

const FALLBACK_COLORS = [getChartColor(4), getChartColor(5), getChartColor(2), getChartColor(3)];

function getSourceColor(source: string, index: number): string {
  return SOURCE_COLORS[source] ?? FALLBACK_COLORS[index % FALLBACK_COLORS.length];
}

function getSourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

/* ------------------------------------------------------------------ */
/* Custom Tooltip                                                      */
/* ------------------------------------------------------------------ */

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;

  const total = payload.reduce((sum, entry) => sum + (entry.value || 0), 0);

  return (
    <div className="rounded-2xl border-0 bg-(--chart-tooltip-bg) px-4 py-3">
      <p className={`${CHART_TOOLTIP_LABEL_CLASS} mb-2`}>{label}</p>
      {payload.map((entry) => (
        <div key={entry.name} className="flex items-center justify-between gap-4 text-xs mb-1">
          <div className="flex items-center gap-2">
            <span
              className="inline-block h-2.5 w-2.5 rounded-full bg-(--c)"
              style={{ "--c": entry.color } as React.CSSProperties}
            />
            <span className="text-(--text-soft)">{getSourceLabel(entry.name)}</span>
          </div>
          <span className={`${CHART_TOOLTIP_VALUE_CLASS} tabular-nums`}>
            {entry.value.toLocaleString()}
          </span>
        </div>
      ))}
      <div className="mt-2 flex items-center justify-between border-t border-(--border) pt-2 text-xs">
        <span className={CHART_TOOLTIP_LABEL_CLASS}>Total</span>
        <span className={`${CHART_TOOLTIP_VALUE_CLASS} tabular-nums`}>
          {total.toLocaleString()}
        </span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Skeleton                                                            */
/* ------------------------------------------------------------------ */

function ChartSkeleton() {
  return (
    <div className="animate-pulse space-y-3">
      <div className="h-4 w-48 rounded bg-(--surface-subtle)" />
      <div className="h-[300px] w-full rounded-2xl bg-(--surface-subtle)" />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Main Component                                                      */
/* ------------------------------------------------------------------ */

type Props = {
  projectId: number | string;
  months?: number;
  className?: string;
  title?: string;
  description?: string;
};

export default function LLMTrafficChart({
  projectId,
  months = 6,
  className = "",
  title,
  description,
}: Props) {
  const { getToken } = useAuth();
  const [data, setData] = useState<LLMTrafficResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [grouped, setGrouped] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      const response = await fetch(
        `/api/v1/projects/${projectId}/monitoring/llm-traffic?months=${months}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (!response.ok) throw new Error("Failed to load LLM traffic data");
      const payload: LLMTrafficResponse = await response.json();
      setData(payload);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "An unexpected error occurred");
    } finally {
      setLoading(false);
    }
  }, [getToken, projectId, months]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  /* Pivot the flat list into { date, chatgpt.com: N, perplexity.ai: N, ... } */
  const { chartData, sources } = useMemo(() => {
    if (!data) return { chartData: [], sources: [] };

    const dateMap: Record<string, ChartRow> = {};
    for (const dp of data.data) {
      if (!dateMap[dp.date]) {
        dateMap[dp.date] = { date: dp.date };
      }
      dateMap[dp.date][dp.source] = ((dateMap[dp.date][dp.source] as number) ?? 0) + dp.sessions;
    }

    return {
      chartData: Object.values(dateMap).sort((a, b) => a.date.localeCompare(b.date)),
      sources: data.sources,
    };
  }, [data]);

  /* Aggregate monthly data for large date ranges */
  const displayData = useMemo(() => {
    if (chartData.length <= 60) return chartData;

    const monthMap: Record<string, ChartRow> = {};
    for (const row of chartData) {
      const monthKey = row.date.slice(0, 7); // YYYY-MM
      if (!monthMap[monthKey]) {
        monthMap[monthKey] = { date: monthKey };
      }
      for (const key of Object.keys(row)) {
        if (key !== "date") {
          monthMap[monthKey][key] =
            ((monthMap[monthKey][key] as number) ?? 0) + ((row[key] as number) ?? 0);
        }
      }
    }
    return Object.values(monthMap).sort((a, b) => a.date.localeCompare(b.date));
  }, [chartData]);

  /* Group by platform family (OpenAI, Google, etc.) when toggle is on */
  const { finalData, finalSources, getLabel, getColor } = useMemo(() => {
    const base = displayData;
    if (!grouped) {
      return {
        finalData: base,
        finalSources: sources,
        getLabel: getSourceLabel,
        getColor: getSourceColor,
      };
    }

    const familySources = [...new Set(sources.map((s) => PLATFORM_FAMILIES[s] ?? s))];
    const familyData = base.map((row) => {
      const out: ChartRow = { date: row.date };
      for (const key of Object.keys(row)) {
        if (key === "date") continue;
        const family = PLATFORM_FAMILIES[key] ?? key;
        out[family] = ((out[family] as number) ?? 0) + ((row[key] as number) ?? 0);
      }
      return out;
    });

    return {
      finalData: familyData,
      finalSources: familySources,
      getLabel: (s: string) => s,
      getColor: (s: string, i: number) =>
        FAMILY_COLORS[s] ?? FALLBACK_COLORS[i % FALLBACK_COLORS.length],
    };
  }, [displayData, sources, grouped]);

  /* ------------------------------------------------------------------ */
  /* Render                                                              */
  /* ------------------------------------------------------------------ */

  if (loading) {
    return (
      <ProjectMonitoringWidgetCard
        icon={Bot}
        title={title ?? "Traffic from AI Models"}
        description={description ?? "Sessions referred by generative AI engines"}
        className={`rounded-2xl border-0 p-6 ${className}`}
      >
        <ChartSkeleton />
      </ProjectMonitoringWidgetCard>
    );
  }

  if (error) {
    return (
      <ProjectMonitoringWidgetCard
        icon={Bot}
        title={title ?? "Traffic from AI Models"}
        description={description ?? "Sessions referred by generative AI engines"}
        className={`rounded-2xl border-0 p-6 ${className}`}
      >
        <ProjectMonitoringWidgetInlineError message={error} />
      </ProjectMonitoringWidgetCard>
    );
  }

  const totalSessions = data?.total_sessions ?? 0;

  return (
    <ProjectMonitoringWidgetCard
      icon={Bot}
      title={title ?? "Traffic from AI Models"}
      description={description ?? "Sessions referred by generative AI engines"}
      className={`rounded-2xl border-0 p-6 ${className}`}
      headerAside={
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setGrouped((v) => !v)}
            className={`flex items-center gap-1.5 rounded-xl border px-2.5 py-1.5 text-[10px] uppercase tracking-wider transition-colors ${
              grouped
                ? "border-primary/40 bg-primary/10 text-primary"
                : "border-(--border) bg-(--surface) text-(--text-muted) hover:border-(--border-hover)"
            }`}
            aria-label="Toggle platform family grouping"
            aria-pressed={grouped}
          >
            <Layers size={12} />
            Group
          </button>
          <div className="flex items-center gap-2 rounded-[22px] border-0 bg-white px-3 py-1.5">
            <TrendingUp size={14} className="text-primary" />
            <span className="text-sm font-bold text-(--foreground) tabular-nums">
              {totalSessions.toLocaleString()}
            </span>
            <span className="text-[10px] uppercase tracking-wider text-(--text-muted)">total</span>
          </div>
        </div>
      }
    >
      {finalData.length === 0 ? (
        <ProjectMonitoringWidgetEmptyState
          icon={Bot}
          title="No AI referral traffic detected yet"
          description="Traffic data will appear here once sessions from AI engines like ChatGPT, Gemini, Copilot, or Perplexity are recorded in your connected GA4 property."
          className="h-[300px]"
        />
      ) : (
        <ResponsiveContainer width="100%" height={320}>
          <AreaChart data={finalData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <defs>
              {finalSources.map((source, i) => (
                <linearGradient
                  key={source}
                  id={`grad-${source.replace(/\W/g, "")}`}
                  x1="0"
                  y1="0"
                  x2="0"
                  y2="1"
                >
                  <stop offset="5%" stopColor={getColor(source, i)} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={getColor(source, i)} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_STROKE} vertical={false} />
            <XAxis
              dataKey="date"
              stroke={CHART_AXIS_STROKE}
              tick={CHART_AXIS_TICK}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              stroke={CHART_AXIS_STROKE}
              tick={CHART_AXIS_TICK}
              tickLine={false}
              axisLine={false}
              width={45}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend
              itemSorter={null}
              verticalAlign="top"
              height={36}
              formatter={(value: string) => (
                <span className={CHART_LEGEND_TEXT_CLASS}>{getLabel(value)}</span>
              )}
            />
            {finalSources.map((source, i) => (
              <Area
                key={source}
                type="monotone"
                dataKey={source}
                stackId="1"
                stroke={getColor(source, i)}
                strokeWidth={2}
                fill={`url(#grad-${source.replace(/\W/g, "")})`}
                animationDuration={1200}
                animationEasing="ease-out"
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      )}
    </ProjectMonitoringWidgetCard>
  );
}
