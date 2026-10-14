"use client";

import React from "react";
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip } from "recharts";
import {
  CHART_AXIS_TICK_SMALL,
  CHART_CURSOR,
  CHART_GRID_STROKE,
  CHART_TOOLTIP_STYLE,
} from "@/components/ui/chartTokens";

type DataPoint = {
  date: string;
  value: number;
};

type MetricBarChartProps = {
  data: DataPoint[];
  label: string;
  color?: string;
  height?: number;
  formatValue?: (v: number) => string;
  className?: string;
};

const defaultFormat = (v: number) => v.toLocaleString();

export default function MetricBarChart({
  data,
  label,
  color = "var(--chart-1)",
  height = 260,
  formatValue = defaultFormat,
  className = "",
}: MetricBarChartProps) {
  if (!data || data.length === 0) {
    return (
      <div
        className={`flex items-center justify-center text-xs text-(--t-3) ${className}`}
        style={{ height }}
      >
        Not enough data to display chart.
      </div>
    );
  }

  return (
    <div className={className} style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_STROKE} />
          <XAxis
            dataKey="date"
            tick={CHART_AXIS_TICK_SMALL}
            tickLine={false}
            axisLine={false}
            tickFormatter={(d: string) => {
              const parts = d.split("-");
              return `${parts[1]}/${parts[2]}`;
            }}
            interval="preserveStartEnd"
            minTickGap={40}
          />
          <YAxis
            tick={CHART_AXIS_TICK_SMALL}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) => formatValue(v)}
            width={42}
          />
          <Tooltip
            cursor={CHART_CURSOR}
            contentStyle={CHART_TOOLTIP_STYLE}
            labelFormatter={(d: string) => d}
            formatter={(value: number) => [formatValue(value), label]}
          />
          <Bar dataKey="value" fill={color} radius={[4, 4, 0, 0]} maxBarSize={24} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
