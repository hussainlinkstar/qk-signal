"use client";

import React from "react";
import Link from "next/link";
import SignalAlert, { SIGNAL_ALERT_ACTION } from "@/components/signal/SignalAlert";
import type { PlanRecommendation } from "@/types/billing";

type Props = {
  recommendation: PlanRecommendation;
  className?: string;
};

export default function PlanRecommendationBanner({ recommendation, className }: Props) {
  if (!recommendation) return null;

  return (
    <SignalAlert
      className={className}
      title={recommendation.message}
      actions={
        <Link href="/dashboard/billing?section=plans" className={SIGNAL_ALERT_ACTION}>
          View {recommendation.recommended_plan_label}
        </Link>
      }
    >
      {recommendation.reasons.length > 0 ? (
        <ul className="list-disc space-y-1 ps-4">
          {recommendation.reasons.map((reason, i) => (
            <li key={i}>{reason}</li>
          ))}
        </ul>
      ) : null}
    </SignalAlert>
  );
}
