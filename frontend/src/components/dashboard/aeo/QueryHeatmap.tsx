import React from "react";
import Card from "@/components/ui/Card";

type QueryCategory = {
  query_type: string;
  count: number;
  percentage: number;
  avg_aeo_score?: number | null;
  median_aeo_score?: number | null;
  win_rate?: number | null;
};

const CATEGORY_ORDER = [
  "instructional",
  "causal",
  "commercial_pricing",
  "commercial_comparison",
  "other",
  "unknown",
] as const;

const CATEGORY_LABELS: Record<string, string> = {
  instructional: "How-to / Instructional",
  causal: "Why / Causal",
  commercial_pricing: "Commercial · Pricing",
  commercial_comparison: "Commercial · Comparison",
  other: "Other",
  unknown: "Unknown",
};

const clamp01 = (value: number): number => Math.min(1, Math.max(0, value));

const asIntensityClass = (avgAeoScore: number | null | undefined): string => {
  const normalized = clamp01((avgAeoScore ?? 0) / 100);
  if (normalized >= 0.75)
    return "bg-cyan-500/30 border-[color-mix(in_srgb,var(--purple)_40%,transparent)] shadow-[0_0_15px_rgba(34,211,238,0.2)]";
  if (normalized >= 0.5)
    return "bg-cyan-500/20 border-[color-mix(in_srgb,var(--purple)_30%,transparent)] shadow-inner";
  if (normalized >= 0.25)
    return "bg-cyan-500/10 border-[color-mix(in_srgb,var(--purple)_20%,transparent)] shadow-inner";
  return "bg-(--line-2) border-(--line) shadow-inner";
};

const sortCategories = (categories: QueryCategory[]): QueryCategory[] => {
  const orderIndex = new Map<string, number>(CATEGORY_ORDER.map((value, index) => [value, index]));
  return [...categories].sort((a, b) => {
    const aOrder = orderIndex.get(a.query_type) ?? Number.MAX_SAFE_INTEGER;
    const bOrder = orderIndex.get(b.query_type) ?? Number.MAX_SAFE_INTEGER;
    if (aOrder !== bOrder) {
      return aOrder - bOrder;
    }
    return b.count - a.count;
  });
};

const toDisplayLabel = (queryType: string): string =>
  CATEGORY_LABELS[queryType] ??
  queryType.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());

const formatScore = (value: number | null | undefined): string =>
  typeof value === "number" && Number.isFinite(value)
    ? `${Math.round(value)} avg AI answers`
    : "AI answers n/a";

export default function QueryHeatmap({ categories }: { categories: QueryCategory[] }) {
  const orderedCategories = sortCategories(categories);

  return (
    <Card className="space-y-4 p-6">
      <div>
        <h3 className="text-lg font-semibold text-(--t-1)">Query Category Heatmap</h3>
        <p className="text-sm text-(--t-2)">
          Color intensity reflects average Answer Engine Index per category.
        </p>
      </div>

      {orderedCategories.length === 0 ? (
        <p className="text-sm text-(--t-2)">No query category data available yet.</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {orderedCategories.map((category) => (
            <div
              key={category.query_type}
              className={`rounded-xl border p-4  transition-all hover:brightness-110 ${asIntensityClass(category.avg_aeo_score)}`}
            >
              <p className="text-sm font-bold text-(--t-1) mb-1">
                {toDisplayLabel(category.query_type)}
              </p>
              <p className="text-xs font-semibold text-(--purple) mb-2">
                {formatScore(category.avg_aeo_score)}
              </p>
              <div className="flex justify-between items-center text-xs text-(--t-2) font-medium">
                <p>{category.count} queries</p>
                <p>{Math.round(category.percentage)}% of total</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
