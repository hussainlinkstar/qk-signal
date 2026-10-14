"use client";

import React from "react";

import Card from "@/components/ui/Card";
import { CARD_LABEL_CLASS } from "@/components/ui/cardStyleTokens";
import {
  RecommendationSeverityBadge,
  type RecommendationSeverity,
} from "@/components/dashboard/scorePrimitives";
import type { GeoStrategicRecommendation } from "@/types/auditResult";

type StrategicRecommendationCardProps = {
  recommendation: GeoStrategicRecommendation;
  category?: string;
  severity?: RecommendationSeverity;
};

export default function StrategicRecommendationCard({
  recommendation,
  category = "Strategic recommendation",
  severity = "medium",
}: StrategicRecommendationCardProps) {
  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-(--border) bg-(--surface-subtle) px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.18em] text-(--text-muted)">
          {category}
        </span>
        <RecommendationSeverityBadge severity={severity} />
      </div>

      <div className="space-y-2">
        <p className={CARD_LABEL_CLASS}>Insight</p>
        <p className="text-sm leading-6 text-(--foreground)">{recommendation.insight}</p>
      </div>

      <div className="space-y-2 rounded border border-(--border) bg-(--surface-subtle) p-4 shadow-(--shadow-inset)">
        <p className={CARD_LABEL_CLASS}>Recommended action</p>
        <p className="text-sm leading-6 text-(--text-soft)">{recommendation.recommended_action}</p>
      </div>
    </Card>
  );
}
