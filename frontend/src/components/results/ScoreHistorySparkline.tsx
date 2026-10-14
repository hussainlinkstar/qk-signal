"use client";

import React from "react";
import { ResponsiveContainer, AreaChart, Area, YAxis, Tooltip as RechartsTooltip } from "recharts";
import type { AuditComparisonHistoryPoint } from "@/hooks/useAuditComparison";
import { CHART_PANEL_CLASS, CHART_TOOLTIP_STYLE } from "@/components/ui/chartTokens";

type ScoreHistorySparklineProps = {
  data: AuditComparisonHistoryPoint[];
  dataKey?: "overall" | "seo" | "geo" | "aeo";
  color?: string;
  height?: number;
  showTooltip?: boolean;
};

function SparkTooltipContent({ active, payload }: any) {
  if (!active || !payload?.[0]) return null;
  const point = payload[0].payload as AuditComparisonHistoryPoint;
  const dateStr = point.date
    ? new Date(point.date).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
      })
    : "";
  return (
    <div className="rounded px-2 py-1 text-[10px] font-bold shadow-lg" style={CHART_TOOLTIP_STYLE}>
      <span className="text-(--foreground)">{Math.round(payload[0].value)}</span>
      <span className="ml-1 text-(--text-muted)">{dateStr}</span>
    </div>
  );
}

export default function ScoreHistorySparkline({
  data,
  dataKey = "overall",
  color = "var(--chart-1)",
  height = 48,
  showTooltip = true,
}: ScoreHistorySparklineProps) {
  if (data.length < 2) return null;

  const gradientId = `sparkHist-${dataKey}`;

  return (
    <div
      className={`h-(--bh) w-full ${CHART_PANEL_CLASS}`}
      style={{ "--bh": height } as React.CSSProperties}
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.3} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <YAxis domain={["dataMin - 5", "dataMax + 5"]} hide />
          {showTooltip && (
            <RechartsTooltip
              content={<SparkTooltipContent />}
              cursor={{ stroke: "var(--selection)", strokeWidth: 1 }}
            />
          )}
          <Area
            type="monotone"
            dataKey={dataKey}
            stroke={color}
            fill={`url(#${gradientId})`}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 3, fill: color, stroke: "var(--background)", strokeWidth: 2 }}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
