"use client";

import React, { useMemo, useState } from "react";
import {
  ResponsiveContainer,
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from "recharts";
import {
  CHART_AXIS_TICK_SMALL,
  CHART_CURSOR,
  CHART_GRID_STROKE,
  CHART_TOOLTIP_STYLE,
} from "@/components/ui/chartTokens";
import { GlassCard } from "@/components/ui/GlassComponents";
import { cx } from "@/components/ui/utils";
import { Spinner } from "@/components/ui/Loading";
import type { ScanUsagePoint } from "@/types/billing";

type Props = {
  dailyUsage: ScanUsagePoint[];
  scanAllowance: number | null;
  isLoading?: boolean;
  error?: string | null;
  className?: string;
};

type RangeOption = { label: string; days: number };
const RANGES: RangeOption[] = [
  { label: "7d", days: 7 },
  { label: "14d", days: 14 },
  { label: "30d", days: 30 },
];

function computeRollingAverage(data: ScanUsagePoint[], window: number): (number | null)[] {
  return data.map((_, i) => {
    if (i < window - 1) return null;
    const slice = data.slice(i - window + 1, i + 1);
    const sum = slice.reduce((acc, d) => acc + d.scans_used, 0);
    return Math.round((sum / window) * 10) / 10;
  });
}

export default function ScanUsageChart({
  dailyUsage,
  scanAllowance,
  isLoading,
  error,
  className,
}: Props) {
  const [range, setRange] = useState(30);

  const chartData = useMemo(() => {
    const sliced = dailyUsage.slice(-range);
    const avg = computeRollingAverage(sliced, 7);
    return sliced.map((d, i) => ({
      date: d.date,
      scans_used: d.scans_used,
      avg_7d: avg[i],
    }));
  }, [dailyUsage, range]);

  const dailyPace =
    scanAllowance !== null && scanAllowance > 0 ? Math.round(scanAllowance / 30) : 0;

  if (isLoading) {
    return (
      <GlassCard className={cx("p-6", className)}>
        <div className="flex h-[300px] items-center justify-center">
          <Spinner size="md" label="Loading usage data..." />
        </div>
      </GlassCard>
    );
  }

  if (error) {
    return (
      <GlassCard className={cx("p-6", className)}>
        <div className="flex h-[300px] items-center justify-center text-sm text-rose-400">
          {error}
        </div>
      </GlassCard>
    );
  }

  return (
    <GlassCard className={cx("space-y-4 p-6", className)}>
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-medium text-(--foreground)">Scan Usage</h3>
          <p className="text-xs text-(--muted-foreground)">
            Daily consumption with 7-day rolling average
          </p>
        </div>
        <div className="flex gap-1 rounded-full border border-(--border) bg-(--surface-subtle) p-0.5">
          {RANGES.map((r) => (
            <button
              key={r.days}
              onClick={() => setRange(r.days)}
              className={cx(
                "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                range === r.days
                  ? "bg-(--primary) text-(--t-1)"
                  : "text-(--muted-foreground) hover:text-(--foreground)"
              )}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {chartData.length === 0 ? (
        <div className="flex h-[260px] items-center justify-center text-sm text-(--muted-foreground)">
          No usage data available yet
        </div>
      ) : (
        <div className="h-[260px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="usageBarGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.9} />
                  <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0.4} />
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
              <YAxis tick={CHART_AXIS_TICK_SMALL} tickLine={false} axisLine={false} width={42} />
              <Tooltip
                cursor={CHART_CURSOR}
                contentStyle={CHART_TOOLTIP_STYLE}
                labelFormatter={(d: string) => d}
                formatter={(value: number, name: string) => [
                  value,
                  name === "scans_used" ? "Scans" : "7d Average",
                ]}
              />
              {dailyPace > 0 && (
                <ReferenceLine
                  y={dailyPace}
                  stroke="var(--chart-3)"
                  strokeDasharray="6 4"
                  strokeOpacity={0.5}
                  label={{
                    value: `~${dailyPace}/day pace`,
                    position: "insideTopRight",
                    fill: "var(--chart-3)",
                    fontSize: 10,
                  }}
                />
              )}
              <Bar
                dataKey="scans_used"
                fill="url(#usageBarGrad)"
                radius={[3, 3, 0, 0]}
                maxBarSize={20}
              />
              <Line
                type="monotone"
                dataKey="avg_7d"
                stroke="var(--chart-2)"
                strokeWidth={2}
                dot={false}
                connectNulls={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="flex items-center gap-6 text-xs text-(--muted-foreground)">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-(--chart-1)" />
          Daily Usage
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 rounded-full bg-(--chart-2)" />
          7-day Average
        </span>
        {dailyPace > 0 && (
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-4 border-t border-dashed border-(--chart-3)" />
            Daily Pace
          </span>
        )}
      </div>
    </GlassCard>
  );
}
