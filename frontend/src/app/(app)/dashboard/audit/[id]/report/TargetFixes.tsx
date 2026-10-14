"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import FixRow from "./FixRow";
import type { ConsolidatedFix } from "@/lib/reportAdapters";

// SIGV2-1218: a prioritised shortlist, and nothing more.
//
// This block used to sum `impactValue` across its three rows and print both
// "+N pts" and a projected destination score ("72 -> 85"). SIGV2-1211 had
// already withdrawn the per-item predicted gain from the Improve tabs, from
// these same fix rows and from the locked-plan preview, on the grounds that a
// predicted gain is a promise about a future measurement the product cannot
// keep. Summing three withdrawn figures and naming the score they arrive at
// is the same claim, only stronger and harder to walk back, so the report had
// ended up declining to promise six points on one action while promising
// thirteen across three.
//
// `impactValue` is a deduction the audit measured, not a recovery it forecast,
// and adding deductions does not produce a forecast either: fixes interact,
// scores are capped and recomputed, and nothing re-measures the claim. An
// honest projection needs real post-fix outcome data, which is SIGV2-1007 and
// does not exist yet, so no replacement figure and no confidence range is
// offered here. Impact stays categorical, in the vocabulary SIGV2-1211
// settled on (`resolveRecommendationImpact`, `signalFixes.plan.impactRated`),
// and `FixRow` is where it is stated.
//
// The ordering is the part that was always true and is the part that is kept.
export default function TargetFixes({ fixes }: { fixes: ConsolidatedFix[] }) {
  const { t } = useTranslation();
  const topFixes = fixes.slice(0, 3);
  if (topFixes.length === 0) return null;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <h2 className="m-0 whitespace-normal! font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
          {t("signalAuditReport.fixes.shortlistTitle", { count: topFixes.length })}
        </h2>
        <div className="h-px flex-1 bg-(--line)" aria-hidden />
      </div>
      <div className="rounded-(--r) border border-(--line) bg-(--panel)">
        {topFixes.map((fix, index) => (
          <FixRow key={`${fix.title}-${index}`} fix={fix} />
        ))}
      </div>
    </div>
  );
}
