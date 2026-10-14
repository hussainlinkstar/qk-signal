"use client";

import React from "react";
import { ResponsiveContainer, AreaChart, Area } from "recharts";
import type { WorkspaceTrendSparklinePoint } from "@/services/workspaceService";
import { CHART_PANEL_CLASS } from "@/components/ui/chartTokens";

type WorkspaceTrendSparklineProps = {
  data: WorkspaceTrendSparklinePoint[];
  color?: string;
};

export default function WorkspaceTrendSparkline({
  data,
  color = "var(--chart-1)",
}: WorkspaceTrendSparklineProps) {
  if (data.length === 0) {
    return (
      <div
        className={`flex h-14 items-center justify-center border-dashed text-[10px] font-black uppercase tracking-[0.18em] text-(--text-soft) ${CHART_PANEL_CLASS}`}
      >
        No trend data
      </div>
    );
  }

  return (
    <div className={`h-14 w-full px-2 ${CHART_PANEL_CLASS}`}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data}>
          <Area
            type="monotone"
            dataKey="overall"
            stroke={color}
            fill={color}
            fillOpacity={0.16}
            strokeWidth={2}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
