"use client";

import React, { useMemo, useState } from "react";
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
import Card from "@/components/ui/Card";
import {
  CHART_AXIS_STROKE,
  CHART_AXIS_TICK,
  CHART_GRID_STROKE,
  CHART_LEGEND_TEXT_CLASS,
  CHART_TOOLTIP_STYLE,
} from "@/components/ui/chartTokens";
import type { MetricTrendPoint } from "@/types/dashboardCharts";
import { formatDate } from "@/lib/dateFormat";

type MetricTrendChartProps = {
  title: string;
  subtitle: string;
  data: MetricTrendPoint[];
  valueLabel: string;
  secondaryValueLabel?: string;
  isLoading?: boolean;
  error?: string;
  seriesDisplay?: "dual" | "toggle";
  signalCoverage?: number | null;
};

type SeriesKey = "value" | "secondaryValue";

const asCalendarDate = (value: string) => {
  return formatDate(value);
};

const getSignalBadge = (
  signalCoverage: number | null
): { label: string; className: string } | null => {
  if (typeof signalCoverage !== "number") {
    return null;
  }

  if (signalCoverage < 0.5) {
    return {
      label: "Low confidence trend",
      className: "border-amber-400/40 bg-amber-500/15 text-amber-100",
    };
  }

  if (signalCoverage < 0.8) {
    return {
      label: "Moderate confidence trend",
      className: "border-sky-400/40 bg-sky-500/15 text-sky-100",
    };
  }

  return {
    label: "High confidence trend",
    className: "border-emerald-400/40 bg-emerald-500/15 text-emerald-100",
  };
};
export default function MetricTrendChart({
  title,
  subtitle,
  data,
  valueLabel,
  secondaryValueLabel,
  isLoading = false,
  error,
  seriesDisplay = "dual",
  signalCoverage = null,
}: MetricTrendChartProps) {
  const hasSecondarySeries = data.some((item) => typeof item.secondaryValue === "number");
  const isToggleMode = hasSecondarySeries && seriesDisplay === "toggle";
  const [activeSeries, setActiveSeries] = useState<SeriesKey>("value");

  const currentSeries = useMemo(
    () =>
      activeSeries === "secondaryValue"
        ? {
            key: "secondaryValue" as const,
            label: secondaryValueLabel ?? "Citations",
            stroke: "var(--chart-4)",
          }
        : {
            key: "value" as const,
            label: valueLabel,
            stroke: "var(--chart-1)",
          },
    [activeSeries, secondaryValueLabel, valueLabel]
  );

  const signalBadge = getSignalBadge(signalCoverage);

  let content: React.ReactNode = null;

  if (isLoading) {
    content = <p className="text-sm text-(--text-muted)">Loading chart history…</p>;
  } else if (error) {
    content = <p className="text-sm text-danger">{error}</p>;
  } else if (data.length === 0) {
    content = (
      <p className="text-sm text-(--text-muted)">
        No metric history yet. Run additional audits to unlock trends.
      </p>
    );
  } else {
    content = (
      <>
        {isToggleMode ? (
          <div
            className="mb-3 flex items-center gap-2"
            role="group"
            aria-label="Chart series toggle"
          >
            <button
              type="button"
              onClick={() => setActiveSeries("value")}
              className={`rounded-md border px-3 py-1 text-xs font-semibold transition ${
                activeSeries === "value"
                  ? "border-primary/20 bg-primary/10 text-primary"
                  : "border-(--border) text-(--text-soft) hover:border-(--border-hover)"
              }`}
            >
              {valueLabel}
            </button>
            <button
              type="button"
              onClick={() => setActiveSeries("secondaryValue")}
              className={`rounded-md border px-3 py-1 text-xs font-semibold transition ${
                activeSeries === "secondaryValue"
                  ? "border-warning/20 bg-warning/10 text-warning"
                  : "border-(--border) text-(--text-soft) hover:border-(--border-hover)"
              }`}
            >
              {secondaryValueLabel ?? "Citations"}
            </button>
          </div>
        ) : null}

        <div className="h-72 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 12, right: 20, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_STROKE} />
              <XAxis
                dataKey="date"
                stroke={CHART_AXIS_STROKE}
                tick={CHART_AXIS_TICK}
                tickLine={false}
                axisLine={false}
                tickFormatter={(value) => asCalendarDate(String(value))}
              />
              <YAxis
                yAxisId="left"
                stroke={isToggleMode ? currentSeries.stroke : CHART_AXIS_STROKE}
                tick={CHART_AXIS_TICK}
                domain={[0, 100]}
                tickLine={false}
                axisLine={false}
              />
              {!isToggleMode && hasSecondarySeries ? (
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  stroke="var(--chart-4)"
                  tick={CHART_AXIS_TICK}
                  tickLine={false}
                  axisLine={false}
                />
              ) : null}
              <Tooltip
                contentStyle={CHART_TOOLTIP_STYLE}
                labelFormatter={(label) => asCalendarDate(String(label))}
                formatter={(value: number, _name, item) => {
                  if (item.dataKey === "secondaryValue") {
                    return [Math.round(value), secondaryValueLabel ?? "Citations"];
                  }

                  return [Math.round(value), valueLabel];
                }}
              />
              {!isToggleMode && hasSecondarySeries ? (
                <Legend
                  itemSorter={null}
                  formatter={(value: string) => (
                    <span className={CHART_LEGEND_TEXT_CLASS}>{value}</span>
                  )}
                />
              ) : null}
              {isToggleMode ? (
                <Line
                  yAxisId="left"
                  type="monotone"
                  dataKey={currentSeries.key}
                  name={currentSeries.label}
                  stroke={currentSeries.stroke}
                  strokeWidth={3}
                  dot={{ r: 3 }}
                />
              ) : (
                <>
                  <Line
                    yAxisId="left"
                    type="monotone"
                    dataKey="value"
                    name={valueLabel}
                    stroke="var(--chart-1)"
                    strokeWidth={3}
                    dot={{ r: 3 }}
                  />
                  {hasSecondarySeries ? (
                    <Line
                      yAxisId="right"
                      type="monotone"
                      dataKey="secondaryValue"
                      name={secondaryValueLabel ?? "Citations"}
                      stroke="var(--chart-4)"
                      strokeWidth={3}
                      dot={{ r: 3 }}
                    />
                  ) : null}
                </>
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </>
    );
  }

  return (
    <Card className="space-y-4 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-xl font-bold tracking-tight text-(--foreground)">{title}</h3>
          <p className="text-sm font-medium text-(--text-muted)">{subtitle}</p>
        </div>
        {signalBadge ? (
          <span
            className={`rounded-full border px-3 py-1 text-xs font-semibold ${signalBadge.className}`}
          >
            {signalBadge.label}
          </span>
        ) : null}
      </div>
      {content}
    </Card>
  );
}
