"use client";

import { Area, AreaChart, ReferenceDot, ResponsiveContainer, XAxis, YAxis } from "recharts";

export type SignalSparklineProps = {
  data: number[];
  color?: string;
  width?: number;
  height?: number;
};

/**
 * Reproduces signal-MVP's hand-rolled `.spark`/`.gspark` sparkline
 * (see /Users/user/signal-MVP/app.js `sparkline()`, lines ~143-155: filled
 * area at 10% opacity under a 1.8px line, with a dot on the last point) using
 * Recharts instead of raw SVG path math, per the shared charting convention
 * already used elsewhere in this codebase.
 */
export default function SignalSparkline({
  data,
  color = "#565E6E",
  width = 56,
  height = 26,
}: SignalSparklineProps) {
  const points = data.map((value, index) => ({ index, value }));
  const last = points[points.length - 1];

  return (
    <div
      className="h-(--bh) w-(--bw)"
      style={{ "--bw": width, "--bh": height } as React.CSSProperties}
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points} margin={{ top: 3, right: 3, bottom: 3, left: 3 }}>
          <XAxis dataKey="index" hide type="number" domain={["dataMin", "dataMax"]} />
          <YAxis hide domain={["dataMin", "dataMax"]} />
          <Area
            type="linear"
            dataKey="value"
            stroke={color}
            strokeWidth={1.8}
            fill={color}
            fillOpacity={0.1}
            dot={false}
            isAnimationActive={false}
          />
          {last && (
            <ReferenceDot x={last.index} y={last.value} r={2.2} fill={color} stroke="none" />
          )}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
