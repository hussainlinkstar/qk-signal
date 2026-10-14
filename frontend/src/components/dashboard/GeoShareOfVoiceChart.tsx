"use client";

import React from "react";
import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  type TooltipContentProps,
} from "recharts";
import Card from "@/components/ui/Card";
import { CHART_TOOLTIP_LABEL_CLASS, CHART_TOOLTIP_VALUE_CLASS } from "@/components/ui/chartTokens";

export type GeoShareOfVoiceDatum = {
  label: "My Site" | "Competitor" | "Others";
  value: number;
  color: string;
};

type GeoShareOfVoiceChartProps = {
  data: GeoShareOfVoiceDatum[];
};

function VoiceTooltip({ active, payload }: Partial<TooltipContentProps<number, string>>) {
  if (!active || !payload?.length) {
    return null;
  }

  const point = payload[0]?.payload as GeoShareOfVoiceDatum | undefined;
  if (!point) {
    return null;
  }

  return (
    <div className="rounded-2xl border border-(--border) bg-(--chart-tooltip-bg) px-4 py-3">
      <p className={CHART_TOOLTIP_VALUE_CLASS}>{point.label}</p>
      <p
        className={`${CHART_TOOLTIP_LABEL_CLASS} mt-1 text-(--c)`}
        style={{ "--c": point.color } as React.CSSProperties}
      >
        {point.value.toFixed(1)}%
      </p>
    </div>
  );
}

export default function GeoShareOfVoiceChart({ data }: GeoShareOfVoiceChartProps) {
  const total = data.reduce((sum, item) => sum + item.value, 0);

  return (
    <Card className="p-6">
      <h3 className="text-xl font-bold tracking-tight text-(--foreground)">
        Citation share of voice
      </h3>
      <p className="mt-1 text-sm font-medium text-(--text-muted)">
        My Site vs competitor across visible citations.
      </p>
      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_220px] lg:items-center">
        <div className="h-64 w-full" role="img" aria-label="Share of voice pie chart">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={data} dataKey="value" nameKey="label" innerRadius={64} outerRadius={92}>
                {data.map((entry) => (
                  <Cell key={entry.label} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip cursor={false} content={<VoiceTooltip />} />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <ul className="space-y-2">
          {data.map((entry) => {
            const percent = total > 0 ? (entry.value / total) * 100 : 0;
            return (
              <li
                key={entry.label}
                className="flex items-center justify-between rounded-xl border border-(--border) bg-(--surface-subtle) px-4 py-3 text-sm transition-colors hover:bg-(--surface)"
              >
                <span className="flex items-center gap-2 text-(--foreground)">
                  <span
                    className="h-2.5 w-2.5 rounded-full bg-(--c)"
                    style={{ "--c": entry.color } as React.CSSProperties}
                  />
                  {entry.label}
                </span>
                <span className="text-(--text-soft)">{percent.toFixed(1)}%</span>
              </li>
            );
          })}
        </ul>
      </div>
    </Card>
  );
}
