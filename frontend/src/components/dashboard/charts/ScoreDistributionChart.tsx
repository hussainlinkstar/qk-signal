"use client";

import React from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import Card from "@/components/ui/Card";
import {
  CHART_AXIS_STROKE,
  CHART_AXIS_TICK,
  CHART_GRID_STROKE,
  CHART_TOOLTIP_STYLE,
} from "@/components/ui/chartTokens";
import type { ScoreDistributionPoint } from "@/types/dashboardCharts";

type ScoreDistributionChartProps = {
  title: string;
  subtitle: string;
  data: ScoreDistributionPoint[];
  isLoading?: boolean;
  error?: string;
};

export default function ScoreDistributionChart({
  title,
  subtitle,
  data,
  isLoading = false,
  error,
}: ScoreDistributionChartProps) {
  let content: React.ReactNode = null;

  if (isLoading) {
    content = <p className="text-sm text-(--text-muted)">Loading score distribution…</p>;
  } else if (error) {
    content = <p className="text-sm text-danger">{error}</p>;
  } else if (data.every((bucket) => bucket.count === 0)) {
    content = (
      <p className="text-sm text-(--text-muted)">
        No completed history is available to plot score ranges.
      </p>
    );
  } else {
    content = (
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 12, right: 20, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_STROKE} />
            <XAxis
              dataKey="bucket"
              stroke={CHART_AXIS_STROKE}
              tick={CHART_AXIS_TICK}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              stroke={CHART_AXIS_STROKE}
              tick={CHART_AXIS_TICK}
              allowDecimals={false}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              contentStyle={CHART_TOOLTIP_STYLE}
              formatter={(value: number) => [`${value}`, "Assessments"]}
            />
            <Bar dataKey="count" fill="var(--chart-1)" radius={[6, 6, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    );
  }

  return (
    <Card className="space-y-4 p-6">
      <div>
        <h3 className="text-lg font-semibold text-(--foreground)">{title}</h3>
        <p className="text-sm text-(--text-muted)">{subtitle}</p>
      </div>
      {content}
    </Card>
  );
}
