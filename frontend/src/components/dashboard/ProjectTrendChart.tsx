"use client";

import React from "react";
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
import type { ProjectTrendPoint } from "@/services/workspaceService";
import {
  CHART_AXIS_STROKE,
  CHART_AXIS_TICK,
  CHART_GRID_STROKE,
  CHART_PANEL_CLASS,
  CHART_TOOLTIP_STYLE,
} from "@/components/ui/chartTokens";

type ProjectTrendChartProps = {
  data: ProjectTrendPoint[];
  visibleSeries: {
    seo: boolean;
    geo: boolean;
    aeo: boolean;
    volatility: boolean;
  };
};

const formatDateLabel = (value: string) => {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
};

export default function ProjectTrendChart({ data, visibleSeries }: ProjectTrendChartProps) {
  if (data.length === 0) {
    return (
      <div
        className={`h-80 ${CHART_PANEL_CLASS} flex items-center justify-center text-sm text-(--text-muted)`}
      >
        Trend history will appear after more audits are completed.
      </div>
    );
  }

  return (
    <div className={`h-80 w-full p-4 ${CHART_PANEL_CLASS}`}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 18, right: 18, left: -10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_STROKE} />
          <XAxis
            dataKey="date"
            tickLine={false}
            axisLine={false}
            stroke={CHART_AXIS_STROKE}
            tick={CHART_AXIS_TICK}
            tickFormatter={formatDateLabel}
          />
          <YAxis
            domain={[0, 100]}
            tickLine={false}
            axisLine={false}
            stroke={CHART_AXIS_STROKE}
            tick={CHART_AXIS_TICK}
          />
          <YAxis
            yAxisId="volatility"
            orientation="right"
            domain={[0, 10]}
            tickLine={false}
            axisLine={false}
            stroke="var(--chart-5)"
            tick={CHART_AXIS_TICK}
          />
          <Tooltip
            labelFormatter={(label) => formatDateLabel(String(label))}
            contentStyle={CHART_TOOLTIP_STYLE}
          />
          <Legend itemSorter={null} />
          {visibleSeries.seo ? (
            <Line
              type="monotone"
              dataKey="seo"
              name="SEO"
              stroke="var(--chart-1)"
              strokeWidth={3}
              dot={{ r: 3 }}
              connectNulls
            />
          ) : null}
          {visibleSeries.geo ? (
            <Line
              type="monotone"
              dataKey="geo"
              name="AI visibility"
              stroke="var(--chart-2)"
              strokeWidth={3}
              dot={{ r: 3 }}
              connectNulls
            />
          ) : null}
          {visibleSeries.aeo ? (
            <Line
              type="monotone"
              dataKey="aeo"
              name="AI answers"
              stroke="var(--chart-3)"
              strokeWidth={3}
              dot={{ r: 3 }}
              connectNulls
            />
          ) : null}
          {visibleSeries.volatility ? (
            <Line
              yAxisId="volatility"
              type="monotone"
              dataKey="volatility_score"
              name="AI Volatility"
              stroke="var(--chart-5)"
              strokeWidth={2}
              strokeDasharray="6 4"
              dot={{ r: 2 }}
              connectNulls
            />
          ) : null}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
