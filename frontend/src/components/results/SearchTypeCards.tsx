"use client";

import React from "react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import GatedSection from "@/components/results/GatedSection";
import { getScoreColor } from "@/lib/scoreColors";
import { isMeasuredSearchType, type SearchType } from "@/lib/reportAdapters";
import { cx } from "@/components/ui/utils";
import { minimumPlanForCapability, requiredPlanLabelForCapability } from "@/lib/planCapabilities";

// The Comparison search type is the competitor-analysis entitlement, so the
// plan this upsell names is read from that capability rather than typed in
// (SIGV2-1221).
const COMPARISON_REQUIRED_PLAN = minimumPlanForCapability("has_competitor_analysis") ?? "";
const COMPARISON_REQUIRED_PLAN_LABEL =
  requiredPlanLabelForCapability("has_competitor_analysis") ?? "a higher plan";

type SearchTypeCardsProps = {
  /** The 5 canonical search types from `getSearchTypes` (backend order). */
  searchTypes: SearchType[];
  /**
   * Whether the user's plan may see premium (Comparison) search types. When
   * `false`, premium cards are blurred behind a Specialist+ upsell. Defaults to
   * `false` (fail-safe) so a premium card stays LOCKED when the capability is
   * unknown or the prop is omitted.
   */
  canSeeComparison?: boolean;
  /** Forwarded to the gated upsell CTA for guest audits. */
  guestAuditToken?: string;
};

const TrendIndicator = ({ trend }: { trend: number | null }) => {
  // "Flat" is a claim that the score was compared with an earlier one and did
  // not move. `aggregate_search_types` never emits a trend, so this rendered on
  // every card forever and asserted a comparison nobody made (SIGV2-1105).
  // A measured zero still reads as flat; an absent trend renders nothing.
  if (typeof trend !== "number" || !Number.isFinite(trend)) {
    return null;
  }
  if (trend === 0) {
    return (
      <span className="flex items-center gap-1 text-[10px] font-bold text-(--t-3)">
        <Minus className="h-3 w-3" />
        Flat
      </span>
    );
  }

  const up = trend > 0;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  return (
    <span
      className={cx(
        "flex items-center gap-1 text-[10px] font-bold",
        up ? "text-emerald-400" : "text-rose-400"
      )}
    >
      <Icon className="h-3 w-3" />
      {up ? "+" : ""}
      {Math.round(trend)}
    </span>
  );
};

const MEASURED_TITLE = "Measured on this project's AI-engine runs";
const UNMEASURED_TITLE = "No AI visibility run has measured this search type yet";

const SourceIndicator = ({ measured }: { measured: boolean }) => (
  <span
    className={cx(
      "flex items-center gap-1 text-[9px] font-bold uppercase tracking-[0.15em]",
      measured ? "text-emerald-400" : "text-(--t-3)"
    )}
    title={measured ? MEASURED_TITLE : UNMEASURED_TITLE}
    aria-label={measured ? MEASURED_TITLE : UNMEASURED_TITLE}
  >
    <span
      aria-hidden="true"
      className={cx("h-1.5 w-1.5 rounded-full", measured ? "bg-emerald-400" : "bg-slate-600")}
    />
    {measured ? "Measured" : "Not measured"}
  </span>
);

const SearchTypeCard = ({ searchType }: { searchType: SearchType }) => {
  // Only this project's own visibility runs produce a score here. The retired
  // "Estimated" state showed an audit sub-score under a search-type label,
  // which is a different quantity, not an approximation (SIGV2-1105).
  const measured = isMeasuredSearchType(searchType);
  const color = measured ? getScoreColor(searchType.score as number) : null;
  const ratio = searchType.answerRatio;

  return (
    <div className="flex h-full flex-col gap-3 rounded border border-(--line) bg-(--line-2) p-4 shadow-inner">
      <div className="flex items-start justify-between gap-2">
        <span className="text-[10px] font-black uppercase tracking-[0.2em] text-(--t-2)">
          {searchType.label}
        </span>
        <TrendIndicator trend={searchType.trend} />
      </div>
      <div className="flex items-baseline gap-1">
        <span className={cx("text-2xl font-black", color ? color.text : "text-(--t-3)")}>
          {measured ? Math.round(searchType.score as number) : "N/A"}
        </span>
        {measured && <span className="text-[10px] font-black text-(--t-3)">/100</span>}
      </div>
      {/* The answers checked for this type, when a run has completed. */}
      {ratio && (
        <p className="text-[10px] font-bold text-(--t-3)">
          {`${ratio.present} of ${ratio.measured} answers`}
        </p>
      )}
      {searchType.insight && (
        <p className="text-[11px] leading-relaxed text-(--t-3)">{searchType.insight}</p>
      )}
      <div className="mt-auto pt-1">
        <SourceIndicator measured={measured} />
      </div>
    </div>
  );
};

/**
 * Renders the 5 customer-facing search-type cards (Brand, Category, Problem,
 * Feature, Comparison) under the AIO drilldown (signal plan Phase 4, Task 4.3).
 * Each card shows the measured per-type score (or "N/A"), the answers checked
 * for the type when a run has completed, and a one-line insight. Premium cards
 * (Comparison) are wrapped in the existing
 * `GatedSection` upsell, blurred with "Upgrade to view", when the plan lacks the
 * comparison/competitor capability (`canSeeComparison === false`).
 */
export default function SearchTypeCards({
  searchTypes,
  canSeeComparison = false,
  guestAuditToken,
}: SearchTypeCardsProps) {
  if (searchTypes.length === 0) {
    return null;
  }

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
      {searchTypes.map((searchType) => {
        const locked = searchType.premium && !canSeeComparison;
        if (locked) {
          return (
            <GatedSection
              key={searchType.id}
              title={`${searchType.label} search type`}
              teaser={`See how you stack up on ${searchType.label.toLowerCase()} queries against rivals.`}
              requiredPlan={COMPARISON_REQUIRED_PLAN}
              requiredPlanLabel={COMPARISON_REQUIRED_PLAN_LABEL}
              guestAuditToken={guestAuditToken}
              className="min-h-[160px]"
              blurredPreview={<SearchTypeCard searchType={searchType} />}
            />
          );
        }

        return <SearchTypeCard key={searchType.id} searchType={searchType} />;
      })}
    </div>
  );
}
