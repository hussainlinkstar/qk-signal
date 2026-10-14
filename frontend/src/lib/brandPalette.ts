export const BRAND_HEX = {
  atlasBlue: "#6366F1",
  atlasBlueHover: "#818CF8",
  signalTeal: "#22D3EE",
  sky300: "#FCA5A5",
  ink950: "#0F172A",
  ink900: "#162033",
  background: "#F8FBFF",
  surface: "#FFFFFF",
  surfaceSubtle: "#EEF3F9",
  border: "#D8E1EE",
  textMuted: "#5B6B84",
  textSoft: "#43526A",
  ring: "#93C5FD",
  success: "#16A34A",
  warning: "#D97706",
  danger: "#DC2626",
  info: "#0EA5E9",
  chart3: "#22D3EE",
  chart4: "#F59E0B",
  chart5: "#EF4444",
  chart6: "#06B6D4",
} as const;

export const BRAND_PRIMARY_PRESETS = [
  "#2563EB", // Sapphire
  "#7C3AED", // Amethyst
  "#059669", // Emerald
  "#DC2626", // Crimson
  "#EA580C", // Tangerine
  "#0891B2", // Cyan
] as const;

export const BRAND_SECONDARY_PRESETS = [
  "#1E293B", // Slate
  "#374151", // Graphite
  "#64748B", // Storm
  "#0F766E", // Deep Teal
  "#4338CA", // Deep Indigo
  "#78716C", // Warm Stone
] as const;

export const BRAND_CHART_HEX_PALETTE = [
  BRAND_HEX.atlasBlue,
  BRAND_HEX.signalTeal,
  BRAND_HEX.chart3,
  BRAND_HEX.chart4,
  BRAND_HEX.chart5,
  BRAND_HEX.chart6,
] as const;
