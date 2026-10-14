"use client";

import React from "react";
import { ResponsiveContainer, AreaChart, Area, YAxis } from "recharts";

type DataPoint = {
  date: string;
  value: number;
};

type MetricSparklineProps = {
  data: DataPoint[];
  /** Stroke / fill colour, defaults to brand teal */
  color?: string;
  height?: number;
  className?: string;
};

export default function MetricSparkline({
  data,
  color = "var(--chart-1)",
  height = 40,
  className = "",
}: MetricSparklineProps) {
  if (!data || data.length < 2) return null;

  const gradientId = `sparkGrad-${color.replace(/[^a-z0-9]+/gi, "") || "chart"}`;

  return (
    <div className={className} style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.3} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <YAxis domain={["dataMin", "dataMax"]} hide />
          <Area
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={1.5}
            fill={`url(#${gradientId})`}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
