"use client";

import React from "react";
import { cx } from "@/components/ui/utils";

type LeadScoreBadgeProps = {
  label: string;
  score: number | null | undefined;
};

function scoreTone(score: number | null | undefined): string {
  if (typeof score !== "number") {
    return "border-slate-600/40 bg-[color-mix(in_srgb,var(--panel)_60%,transparent)] text-(--t-2)";
  }
  if (score >= 80) {
    return "border-emerald-500/40 bg-emerald-500/10 text-emerald-300";
  }
  if (score >= 60) {
    return "border-amber-500/40 bg-amber-500/10 text-amber-300";
  }
  return "border-rose-500/40 bg-rose-500/10 text-rose-300";
}

export default function LeadScoreBadge({ label, score }: LeadScoreBadgeProps) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] font-bold uppercase tracking-wider",
        scoreTone(score)
      )}
      aria-label={`${label} score`}
    >
      <span>{label}</span>
      <span>{typeof score === "number" ? Math.round(score) : "--"}</span>
    </span>
  );
}
