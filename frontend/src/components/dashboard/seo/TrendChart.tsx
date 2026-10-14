"use client";

import React from "react";
import { motion, useReducedMotion } from "motion/react";
import MetricTrendChart from "@/components/dashboard/charts/MetricTrendChart";
import Card from "@/components/ui/Card";
import type { MetricTrendPoint } from "@/types/dashboardCharts";

type TrendChartProps = {
  data: MetricTrendPoint[];
  isLoading?: boolean;
  error?: string | null;
  isEmpty?: boolean;
};

export default function TrendChart({
  data,
  isLoading = false,
  error = null,
  isEmpty = false,
}: TrendChartProps) {
  const shouldReduceMotion = useReducedMotion();

  return (
    <motion.div
      initial={shouldReduceMotion ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={shouldReduceMotion ? { duration: 0 } : { duration: 0.3, ease: "easeOut" }}
    >
      {isEmpty && !isLoading && !error ? (
        <Card className="space-y-4 p-6">
          <div>
            <h3 className="text-lg font-semibold text-(--t-1)">SEO trend</h3>
            <p className="text-sm text-(--t-2)">
              How your SEO score changed over completed assessments.
            </p>
          </div>
          <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-4 text-sm font-medium text-amber-200 shadow-inner">
            Insufficient history: you need at least 2 completed assessments for trend analysis.
          </div>
        </Card>
      ) : (
        <MetricTrendChart
          title="SEO trend"
          subtitle="How your SEO score changed over completed assessments."
          data={data}
          valueLabel="SEO score"
          isLoading={isLoading}
          error={error ?? undefined}
        />
      )}
    </motion.div>
  );
}
