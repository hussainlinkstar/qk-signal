"use client";

import React from "react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
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

type MetricLineChartProps = {
  data: DataPoint[];
  label: string;
  color?: string;
  height?: number;
  formatValue?: (v: number) => string;
  className?: string;
};

const defaultFormat = (v: number) => v.toLocaleString();

export default function MetricLineChart({
  data,
  label,
  color = "var(--chart-2)",
  height = 260,
  formatValue = defaultFormat,
  className = "",
}: MetricLineChartProps) {
  const gradientId = `lineGrad-${color.replace(/[^a-z0-9]+/gi, "") || "chart"}`;

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
        <AreaChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.2} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
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
            width={52}
          />
          <Tooltip
            cursor={CHART_CURSOR}
            contentStyle={CHART_TOOLTIP_STYLE}
            labelFormatter={(d: string) => d}
            formatter={(value: number) => [formatValue(value), label]}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={2}
            fill={`url(#${gradientId})`}
            dot={false}
            activeDot={{ r: 4, fill: color, stroke: "var(--panel)", strokeWidth: 2 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
