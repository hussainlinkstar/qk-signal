import type { CSSProperties } from "react";

export const CHART_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
  "var(--chart-6)",
] as const;

export const CHART_PANEL_CLASS = "rounded-2xl border-0 bg-(--surface-subtle)";
export const CHART_EMPTY_STATE_CLASS =
  "flex items-center justify-center rounded-2xl border-0 bg-(--surface-subtle) text-sm text-(--text-muted)";
export const CHART_TOOLTIP_LABEL_CLASS = "text-xs font-semibold text-(--text-muted)";
export const CHART_TOOLTIP_VALUE_CLASS = "font-semibold text-(--foreground)";
export const CHART_LEGEND_TEXT_CLASS = "text-xs font-medium text-(--text-soft)";

export const CHART_GRID_STROKE = "var(--chart-grid)";
export const CHART_AXIS_STROKE = "var(--chart-axis)";
export const CHART_AXIS_TICK = {
  fill: "var(--chart-axis)",
  fontSize: 11,
  fontWeight: 600,
} as const;
export const CHART_AXIS_TICK_SMALL = {
  fill: "var(--chart-axis)",
  fontSize: 10,
  fontWeight: 600,
} as const;

export const CHART_TOOLTIP_STYLE: CSSProperties = {
  borderRadius: "var(--chart-tooltip-radius, 18px)",
  border: "1px solid var(--border)",
  backgroundColor: "var(--chart-tooltip-bg)",
  boxShadow: "var(--chart-tooltip-shadow)",
  color: "var(--foreground)",
};

export const CHART_CURSOR = {
  fill: "var(--selection)",
};

export const getChartColor = (index: number) => CHART_COLORS[index % CHART_COLORS.length];
