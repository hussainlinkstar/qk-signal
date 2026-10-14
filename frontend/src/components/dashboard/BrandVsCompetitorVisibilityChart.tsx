"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import { AlertCircle, BarChart3, Clock, Lock, TrendingUp, Users } from "lucide-react";

import Button from "@/components/ui/Button";
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
  CARD_SUBSECTION_SURFACE_CLASS,
  DASHBOARD_CARD_CLASS,
} from "@/components/ui/cardStyleTokens";
import { TYPO } from "@/components/ui/typographyTokens";
import { formatDate } from "@/lib/dateFormatShared";
import { requestJson } from "@/services/http";
import type { ComparativeVisibilityResponse, VisibilityProvider } from "@/types/monitoring";
import {
  VISIBILITY_PROVIDER_LABELS,
  formatVisibilityPercent,
  measuredVisibilityProviders,
  offeredVisibilityProviders,
} from "@/components/dashboard/visibilityUtils";
import { requiredPlanLabelForCapability } from "@/lib/planCapabilities";

const COMPARISON_REQUIRED_PLAN_LABEL = requiredPlanLabelForCapability("has_competitor_analysis");

// SIGV2-1215: Copilot ("bing") was a tab here until it was withdrawn from the
// product. A filter option is an offer to measure that engine, so it goes with
// the measurement. The list runs through the offered filter as well, so the
// withdrawal flag governs it rather than this literal alone.
const PROVIDER_TABS: VisibilityProvider[] = offeredVisibilityProviders<VisibilityProvider>([
  "google",
  "openai",
  "anthropic",
  "perplexity",
]);

const SECONDS_PER_DAY = 24 * 60 * 60;

const BRAND_COLOR = "var(--primary)";
const COMPETITOR_COLORS = [
  getChartColor(1),
  getChartColor(3),
  getChartColor(4),
  getChartColor(5),
  getChartColor(2),
];
const SOV_COLORS = [BRAND_COLOR, ...COMPETITOR_COLORS];

type Props = {
  projectId: string;
};

function CompTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-2xl border border-(--border) bg-(--chart-tooltip-bg) px-4 py-3">
      <p className={CHART_TOOLTIP_LABEL_CLASS}>{label}</p>
      <div className="mt-2 space-y-2">
        {payload.map((e) => (
          <div key={e.name} className="flex items-center justify-between gap-6 text-xs">
            <div className="flex items-center gap-2 text-(--text-soft)">
              <span
                className="h-2.5 w-2.5 rounded-full bg-(--c)"
                style={{ "--c": e.color } as React.CSSProperties}
              />
              <span>{e.name}</span>
            </div>
            <span className={CHART_TOOLTIP_VALUE_CLASS}>{Math.round(e.value)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function BrandVsCompetitorVisibilityChart({ projectId }: Props) {
  const { t } = useTranslation();
  const [data, setData] = useState<ComparativeVisibilityResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // SIGV2-1302: no engine is chosen until the roster says which are measured.
  //
  // This used to initialise to "google", the one engine Specialist stopped
  // measuring, and correct itself in an effect once `allowed_providers`
  // arrived. An effect runs after the paint, so the chart published a frame
  // showing Gemini's frozen score to a plan that no longer measures it, and
  // `planUnmeasuredEngines.test.tsx` caught it intermittently depending on
  // which render pass its assertion landed in. "Briefly" still counts: the
  // rule in SIGV2-1216 is that no surface renders such an engine.
  //
  // `null` means "not chosen yet" and the active provider is derived below,
  // so the disallowed value never exists in state at all.
  const [chosenProvider, setChosenProvider] = useState<VisibilityProvider | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await requestJson<ComparativeVisibilityResponse>({
        endpoint: `/api/v1/projects/${projectId}/monitoring/visibility-comparative?days=90`,
        method: "GET",
        errorMessage: "Failed to load competitor visibility data.",
      });
      setData(res);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 402) {
        setError("upgrade");
      } else {
        setError("Failed to load competitor visibility data.");
      }
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // SIGV2-1216: a tab is an offer to show a measurement, so the plan's roster
  // decides the list, not a literal. The default below is "google", which is
  // exactly the engine Specialist stops measuring, so without this a
  // Specialist project opens this chart on an engine it no longer measures.
  const providerTabs = useMemo(
    () => measuredVisibilityProviders<VisibilityProvider>(PROVIDER_TABS, data?.allowed_providers),
    [data?.allowed_providers]
  );

  // Derived, not corrected: the customer's choice when it is still measured,
  // otherwise the first engine the plan does measure, otherwise nothing.
  const activeProvider: VisibilityProvider | null =
    chosenProvider && providerTabs.includes(chosenProvider)
      ? chosenProvider
      : (providerTabs[0] ?? null);

  const setActiveProvider = setChosenProvider;

  const domainEntries = useMemo(() => {
    if (!data) return [];
    return Object.entries(data.domains).sort(
      ([, a], [, b]) => (b.is_primary ? 1 : 0) - (a.is_primary ? 1 : 0)
    );
  }, [data]);

  const brandEntry = domainEntries.find(([, d]) => d.is_primary);
  const competitorEntries = domainEntries.filter(([, d]) => !d.is_primary);

  const chartData = useMemo(() => {
    if (!data || domainEntries.length === 0) return [];

    const dateSet = new Set<string>();
    for (const [, d] of domainEntries) {
      for (const pt of d.trend) dateSet.add(pt.date);
    }

    const sortedDates = Array.from(dateSet).sort();
    return sortedDates.map((date) => {
      const row: Record<string, string | number | null> = { date };
      for (const [domain, d] of domainEntries) {
        const pt = d.trend.find((t) => t.date === date);
        row[d.label || domain] = pt?.scores[activeProvider] ?? null;
      }
      return row;
    });
  }, [data, domainEntries, activeProvider]);

  // SIGV2-1208: scheduled competitor measurement runs on a slower cadence than
  // the project's own domain, so these rows can legitimately be days older than
  // the brand row beside them. The age and the cadence it is measured against
  // are both stated, and a reading past its own cadence is called overdue
  // rather than left to read as current.
  const freshness = useMemo(() => {
    const measuredAt = data?.competitors_last_measured_at ?? null;
    const intervalSeconds = data?.competitor_sweep_interval_seconds ?? null;
    const overdue =
      measuredAt !== null &&
      intervalSeconds !== null &&
      (Date.now() - new Date(measuredAt).getTime()) / 1000 > intervalSeconds;
    return {
      label:
        measuredAt === null
          ? t("signalCompetitorVisibility.freshnessNever")
          : t("signalCompetitorVisibility.freshnessMeasured", {
              date: formatDate(measuredAt),
            }),
      cadence:
        intervalSeconds === null
          ? t("signalCompetitorVisibility.cadenceOnDemand")
          : t("signalCompetitorVisibility.cadenceDays", {
              count: Math.max(1, Math.round(intervalSeconds / SECONDS_PER_DAY)),
            }),
      overdue,
    };
  }, [data, t]);

  const sovData = useMemo(() => {
    if (!domainEntries.length) return [];
    return domainEntries.map(([, d], idx) => ({
      name: d.label,
      value: d.share_of_voice ?? 0,
      fill: d.is_primary ? SOV_COLORS[0] : SOV_COLORS[(idx % (SOV_COLORS.length - 1)) + 1],
    }));
  }, [domainEntries]);

  // --- Render states ---
  if (loading) {
    return (
      <Card className={`${CARD_CONTAINER_PRESETS.primary} ${DASHBOARD_CARD_CLASS}`}>
        <div className="animate-pulse space-y-4">
          <div className="h-3 w-40 rounded bg-(--surface-subtle)" />
          <div className="h-7 w-64 rounded bg-(--surface-subtle)" />
          <div className="h-80 rounded-2xl bg-(--surface-subtle)" />
        </div>
      </Card>
    );
  }

  if (error === "upgrade") {
    return (
      <Card className={`${CARD_CONTAINER_PRESETS.primary} ${DASHBOARD_CARD_CLASS}`}>
        <div className="flex items-start gap-4">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-amber-500/10">
            <Lock className="h-5 w-5 text-amber-400" />
          </div>
          <div className="space-y-2">
            <p className={CARD_LABEL_CLASS}>Competitor Visibility</p>
            <h2 className={TYPO.sectionTitle}>Brand vs Competitor AI Visibility</h2>
            {/* SIGV2-1221: the plan is derived from the capability the
                endpoint gates on, so this sentence cannot name a plan the
                backend does not require. */}
            <p className="text-sm text-(--text-soft)">
              {COMPARISON_REQUIRED_PLAN_LABEL
                ? `Competitor AI visibility comparison requires ${COMPARISON_REQUIRED_PLAN_LABEL} or higher.`
                : "Competitor AI visibility comparison is not available on this plan."}
            </p>
          </div>
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
            <p className={CARD_LABEL_CLASS}>Competitor Visibility</p>
            <h2 className={TYPO.sectionTitle}>Brand vs Competitor AI Visibility</h2>
            <p className="mt-2 text-sm text-(--text-muted)">{error}</p>
          </div>
        </div>
        <Button size="sm" variant="ghost" onClick={fetchData}>
          Retry
        </Button>
      </Card>
    );
  }

  if (!data || competitorEntries.length === 0) {
    return (
      <Card className={`${CARD_CONTAINER_PRESETS.primary} ${DASHBOARD_CARD_CLASS}`}>
        <div className="flex items-start gap-4">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10">
            <Users className="h-5 w-5 text-primary" />
          </div>
          <div className="space-y-2">
            <p className={CARD_LABEL_CLASS}>Competitor Visibility</p>
            <h2 className={TYPO.sectionTitle}>Brand vs Competitor AI Visibility</h2>
            <p className="text-sm text-(--text-soft)">
              Add competitors to your project to compare AI visibility across engines.
            </p>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card className={`${CARD_CONTAINER_PRESETS.primary} ${DASHBOARD_CARD_CLASS}`}>
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <p className={CARD_LABEL_CLASS}>Competitor Visibility</p>
          <h2 className={TYPO.sectionTitle}>Brand vs Competitor AI Visibility</h2>
        </div>
        <div className="flex flex-col items-start gap-2 md:items-end">
          <div className="inline-flex items-center gap-2 rounded-full border border-(--border) bg-(--surface) px-3 py-1.5 text-xs font-semibold text-(--text-soft)">
            <TrendingUp className="h-4 w-4 text-primary" />
            Last 90 days
          </div>
          <div
            data-testid="competitor-freshness"
            className={`inline-flex items-center gap-2 text-xs font-semibold ${
              freshness.overdue ? "text-warning" : "text-(--text-soft)"
            }`}
          >
            <Clock className="h-3.5 w-3.5" />
            <span>{freshness.label}</span>
            {freshness.overdue && (
              <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] uppercase tracking-wider text-amber-400">
                {t("signalCompetitorVisibility.freshnessOverdue")}
              </span>
            )}
          </div>
          <p
            data-testid="competitor-cadence"
            className="text-[10px] uppercase tracking-wider text-(--text-muted)"
          >
            {freshness.cadence}
          </p>
        </div>
      </div>

      {/* Provider tabs */}
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="AI provider filter">
        {providerTabs.map((prov) => (
          <button
            key={prov}
            role="tab"
            aria-selected={activeProvider === prov}
            onClick={() => setActiveProvider(prov)}
            className={`rounded px-3 py-1.5 text-xs font-semibold transition-colors ${
              activeProvider === prov
                ? "bg-primary/15 text-primary"
                : "bg-(--surface-subtle) text-(--text-muted) hover:text-(--text-soft)"
            }`}
          >
            {VISIBILITY_PROVIDER_LABELS[prov]}
          </button>
        ))}
      </div>

      {/* Share-of-Voice summary bar */}
      {brandEntry && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {domainEntries.map(([domain, d], idx) => {
            const provStats = d.providers[activeProvider];
            const score = provStats?.visibility_score ?? null;
            return (
              <div key={domain} className={`${CARD_SUBSECTION_SURFACE_CLASS} space-y-2`}>
                <div className="flex items-center gap-2">
                  <span
                    className="h-2.5 w-2.5 rounded-full bg-(--c)"
                    style={
                      {
                        "--c": d.is_primary
                          ? BRAND_COLOR
                          : COMPETITOR_COLORS[(idx - 1) % COMPETITOR_COLORS.length],
                      } as React.CSSProperties
                    }
                  />
                  <p className="truncate text-xs font-semibold text-(--text-soft)">
                    {d.label}
                    {d.is_primary ? " (You)" : ""}
                  </p>
                </div>
                <p className="text-2xl font-semibold text-(--foreground)">
                  {formatVisibilityPercent(score)}
                </p>
                {d.share_of_voice !== null && (
                  <p className="text-[10px] uppercase tracking-wider text-(--text-muted)">
                    SoV: {d.share_of_voice}%
                  </p>
                )}
                {/* Each card dates its own figure: the domains are measured on
                    different clocks, so one card's freshness says nothing
                    about the next one's. */}
                <p
                  data-testid={`domain-measured-${domain}`}
                  className="text-[10px] uppercase tracking-wider text-(--text-muted)"
                >
                  {d.last_measured_at
                    ? t("signalCompetitorVisibility.domainMeasured", {
                        date: formatDate(d.last_measured_at),
                      })
                    : t("signalCompetitorVisibility.domainNever")}
                </p>
              </div>
            );
          })}
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        {/* Trend chart */}
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
              <Tooltip content={<CompTooltip />} />
              <Legend
                itemSorter={null}
                formatter={(value: string) => (
                  <span className={CHART_LEGEND_TEXT_CLASS}>{value}</span>
                )}
              />
              {domainEntries.map(([domain, d], idx) => (
                <Line
                  key={domain}
                  type="monotone"
                  dataKey={d.label || domain}
                  stroke={
                    d.is_primary
                      ? BRAND_COLOR
                      : COMPETITOR_COLORS[(idx - 1) % COMPETITOR_COLORS.length]
                  }
                  strokeWidth={d.is_primary ? 3 : 2}
                  strokeDasharray={d.is_primary ? undefined : "6 3"}
                  dot={d.is_primary ? { r: 3 } : false}
                  activeDot={{ r: 5 }}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Share-of-Voice pie */}
        <div className="flex flex-col items-center gap-3">
          <p className={CARD_LABEL_CLASS}>Share of Voice</p>
          <div className="h-52 w-52">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={sovData}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  innerRadius={45}
                  outerRadius={75}
                  paddingAngle={2}
                  strokeWidth={0}
                >
                  {sovData.map((entry, idx) => (
                    <Cell key={idx} fill={entry.fill} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(value: number) => `${Math.round(value)}%`}
                  contentStyle={{
                    borderRadius: "12px",
                    border: "1px solid var(--border)",
                    backgroundColor: "var(--chart-tooltip-bg)",
                    color: "var(--foreground)",
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="space-y-1">
            {sovData.map((entry) => (
              <div key={entry.name} className="flex items-center gap-2 text-xs text-(--text-soft)">
                <span
                  className="h-2 w-2 rounded-full bg-(--c)"
                  style={{ "--c": entry.fill } as React.CSSProperties}
                />
                <span className="truncate">{entry.name}</span>
                <span className="ml-auto tabular-nums">{Math.round(entry.value)}%</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="inline-flex items-center gap-2 text-xs text-(--text-soft)">
        <BarChart3 className="h-4 w-4" />
        Share of Voice = your citations / (your + competitor citations) across all tracked queries.
      </div>
    </Card>
  );
}
