"use client";

import React from "react";
import { Zap } from "lucide-react";
import { getScoreColor } from "@/lib/scoreColors";

const MetricIndicator = ({
  label,
  value,
  score,
}: {
  label: string;
  value: string;
  score: number;
}) => {
  const colorClasses = getScoreColor(score);

  return (
    <div className="flex items-center justify-between py-3">
      <p className="text-(--t-2)">{label}</p>
      <div className="flex items-center">
        <span className="font-semibold text-(--t-1) mr-3">{value}</span>
        <span className={`w-3 h-3 rounded-full ${colorClasses.bg}`}></span>
      </div>
    </div>
  );
};

type PerformanceMetrics = {
  performance_score?: number;
  first_contentful_paint?: string;
  largest_contentful_paint?: string;
  speed_index?: string;
  total_blocking_time?: string;
  interaction_to_next_paint?: string;
  cumulative_layout_shift?: string;
};

const TechnicalMetrics = ({ metrics }: { metrics: PerformanceMetrics | null | undefined }) => {
  const {
    performance_score = 0,
    first_contentful_paint = "N/A",
    largest_contentful_paint = "N/A",
    speed_index = "N/A",
    total_blocking_time = "N/A",
    interaction_to_next_paint = "N/A",
    cumulative_layout_shift = "N/A",
  } = metrics ?? {};

  const getNumericValue = (value: string) => {
    if (!value || value === "N/A") return null;
    const cleanValue = value.replace(/[^\d.]/g, "");
    if (!cleanValue) return null;
    const numericValue = parseFloat(cleanValue);
    return Number.isFinite(numericValue) ? numericValue : null;
  };

  const getTimeScore = (
    value: string,
    goodThreshold: number,
    needsImprovementThreshold: number
  ) => {
    const numericValue = getNumericValue(value);
    if (numericValue === null) return 0;
    if (numericValue <= goodThreshold) return 95;
    if (numericValue <= needsImprovementThreshold) return 60;
    return 20;
  };

  const getMetricScore = (
    value: string,
    metric: "fcp" | "lcp" | "speedIndex" | "tbt" | "inp" | "cls"
  ) => {
    if (metric === "cls") {
      const numericValue = getNumericValue(value);
      if (numericValue === null) return 0;
      if (numericValue <= 0.1) return 95;
      if (numericValue <= 0.25) return 60;
      return 20;
    }

    if (metric === "tbt") return getTimeScore(value, 200, 600);
    if (metric === "inp") return getTimeScore(value, 200, 500);
    if (metric === "fcp") return getTimeScore(value, 1.8, 3.0);
    if (metric === "speedIndex") return getTimeScore(value, 3.4, 5.8);
    return getTimeScore(value, 2.5, 4.0);
  };

  return (
    <div className="p-6 bg-(--panel) rounded-lg border border-(--line)">
      <div className="flex items-center text-yellow-400 mb-4">
        <Zap className="w-6 h-6 mr-2" />
        <h3 className="text-xl font-semibold">PageSpeed Insights</h3>
      </div>
      <div className="divide-y divide-slate-800">
        <MetricIndicator
          label="Overall Performance"
          value={`${Math.round(performance_score)}%`}
          score={performance_score}
        />
        <MetricIndicator
          label="First Contentful Paint"
          value={first_contentful_paint ?? "N/A"}
          score={getMetricScore(first_contentful_paint, "fcp")}
        />
        <MetricIndicator
          label="Largest Contentful Paint"
          value={largest_contentful_paint ?? "N/A"}
          score={getMetricScore(largest_contentful_paint, "lcp")}
        />
        <MetricIndicator
          label="Speed Index"
          value={speed_index ?? "N/A"}
          score={getMetricScore(speed_index, "speedIndex")}
        />
        <MetricIndicator
          label="Total Blocking Time"
          value={total_blocking_time ?? "N/A"}
          score={getMetricScore(total_blocking_time, "tbt")}
        />
        <MetricIndicator
          label="Interaction to Next Paint"
          value={interaction_to_next_paint ?? "N/A"}
          score={getMetricScore(interaction_to_next_paint, "inp")}
        />
        <MetricIndicator
          label="Cumulative Layout Shift"
          value={cumulative_layout_shift ?? "N/A"}
          score={getMetricScore(cumulative_layout_shift, "cls")}
        />
      </div>
    </div>
  );
};

export default TechnicalMetrics;
