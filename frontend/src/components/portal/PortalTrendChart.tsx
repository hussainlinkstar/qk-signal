"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PortalTrendPoint } from "@/services/portalService";
import {
  CHART_AXIS_STROKE,
  CHART_AXIS_TICK,
  CHART_GRID_STROKE,
  CHART_PANEL_CLASS,
  CHART_TOOLTIP_STYLE,
} from "@/components/ui/chartTokens";

type PortalTrendChartProps = {
  data: PortalTrendPoint[];
  primaryColor: string;
  secondaryColor: string;
};

const formatLabel = (value: string | null) => {
  if (!value) {
    return "Pending";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Pending";
  }

  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
};

const normalizeData = (data: PortalTrendPoint[]) =>
  data.map((point, index) => ({
    key: point.created_at ?? `point-${index}`,
    label: formatLabel(point.created_at),
    seo: typeof point.seo_score === "number" ? Math.round(point.seo_score) : null,
    geo: typeof point.geo_score === "number" ? Math.round(point.geo_score) : null,
    aeo: typeof point.aeo_score === "number" ? Math.round(point.aeo_score) : null,
  }));

export default function PortalTrendChart({
  data,
  primaryColor,
  secondaryColor,
}: PortalTrendChartProps) {
  const chartData = normalizeData(data);

  if (chartData.length === 0) {
    return (
      <div
        className={`h-72 ${CHART_PANEL_CLASS} flex items-center justify-center text-sm text-(--text-muted)`}
      >
        Trend history will appear after more audits are completed.
      </div>
    );
  }

  return (
    <div className={`h-72 w-full p-4 ${CHART_PANEL_CLASS}`}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 16, right: 12, left: -16, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_STROKE} />
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={false}
            stroke={CHART_AXIS_STROKE}
            tick={CHART_AXIS_TICK}
          />
          <YAxis
            domain={[0, 100]}
            tickLine={false}
            axisLine={false}
            stroke={CHART_AXIS_STROKE}
            tick={CHART_AXIS_TICK}
          />
          <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
          <Line
            type="monotone"
            dataKey="seo"
            name="SEO"
            stroke={primaryColor}
            strokeWidth={3}
            dot={{ r: 3 }}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="geo"
            name="AI visibility"
            stroke={secondaryColor}
            strokeWidth={3}
            dot={{ r: 3 }}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="aeo"
            name="AI answers"
            stroke="var(--chart-4)"
            strokeWidth={3}
            dot={{ r: 3 }}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
