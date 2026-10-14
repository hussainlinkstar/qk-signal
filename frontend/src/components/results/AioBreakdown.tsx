"use client";

import React from "react";
import { Sparkles } from "lucide-react";
import GeoIcon from "@/components/ui/GeoIcon";
import SearchTypeCards from "@/components/results/SearchTypeCards";
import { getScoreColor } from "@/lib/scoreColors";
import type { AioView, SearchType } from "@/lib/reportAdapters";
import type { RoleMode } from "@/lib/roleMode";
import { describeScore } from "@/lib/copy/signalCopy";
import { cx } from "@/components/ui/utils";

type AioBreakdownProps = {
  /** The derived AIO roll-up view (score + AEO/GEO components). */
  aioView: AioView | null;
  /**
   * Active persona role mode. Used to render a deterministic, role-appropriate
   * interpretation of the AIO score via `describeScore`. Defaults to "marketer".
   */
  role?: RoleMode;
  /** Rendered AEO panel — the existing AeoTab content, supplied by the caller. */
  aeoPanel: React.ReactNode;
  /** Rendered GEO panel — the existing GeoTab content, supplied by the caller. */
  geoPanel: React.ReactNode;
  /** The 5 customer-facing search types (`getSearchTypes`); empty hides the row. */
  searchTypes?: SearchType[];
  /** Whether the plan may see the premium Comparison card (else blurred upsell). */
  canSeeComparison?: boolean;
  /** Forwarded to the gated upsell CTA for guest audits. */
  guestAuditToken?: string;
};

const ComponentScore = ({ label, score }: { label: string; score: number | null }) => {
  const hasScore = typeof score === "number";
  const color = hasScore ? getScoreColor(score) : null;
  return (
    <div className="flex items-center gap-2 rounded-full border border-(--line) bg-(--line-2) px-3 py-1">
      <span className="text-[9px] font-bold uppercase tracking-widest text-(--t-2)">{label}</span>
      <span className={cx("text-[11px] font-black", color ? color.text : "text-(--t-3)")}>
        {hasScore ? `${Math.round(score)}/100` : "N/A"}
      </span>
    </div>
  );
};

/**
 * AIO drilldown — groups the existing AEO + GEO panel content under a single
 * customer-facing "AI engine visibility & reputation" view. AIO is a derived,
 * additive presentation of the unchanged AEO/GEO engine outputs (signal plan
 * Phase 2, Task 2.4). The AEO/GEO panels are passed in as nodes so this stays
 * presentational and does not duplicate the tab logic.
 */
export default function AioBreakdown({
  aioView,
  role = "marketer",
  aeoPanel,
  geoPanel,
  searchTypes = [],
  canSeeComparison = false,
  guestAuditToken,
}: AioBreakdownProps) {
  const aioScore = aioView?.aio_score ?? null;
  const aioColor = typeof aioScore === "number" ? getScoreColor(aioScore) : null;
  // Deterministic, role-appropriate read of the AIO pillar score. Routed
  // through the copy layer so no banned jargon leaks onto this surface.
  const aioCopy = describeScore("aio", aioScore, role);

  return (
    <section
      aria-label="AI engine visibility & reputation"
      className="space-y-10 rounded border border-(--line) bg-(--line-2) p-6 shadow-inner"
    >
      <header className="flex flex-col gap-4 border-b border-(--line) pb-6 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <h3 className="flex items-center gap-3 text-sm font-black uppercase tracking-[0.2em] text-(--t-1)">
            <Sparkles className="h-4 w-4 text-primary" />
            AI engine visibility &amp; reputation
          </h3>
          <p className="text-[10px] font-bold uppercase tracking-widest text-(--t-3)">
            Website &amp; Brand · AI answers + AI visibility roll-up
          </p>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <ComponentScore label="AI answers" score={aioView?.components.aeo ?? null} />
            <ComponentScore label="AI visibility" score={aioView?.components.geo ?? null} />
          </div>
          <p className="max-w-prose text-[11px] leading-relaxed text-(--t-2)">
            {aioCopy.interpretation}
          </p>
          {aioCopy.nextAction && (
            <p className="text-[10px] font-bold uppercase tracking-widest text-(--t-3)">
              {aioCopy.nextAction}
            </p>
          )}
        </div>
        <div className="flex items-baseline gap-1">
          <span className={cx("text-3xl font-black", aioColor ? aioColor.text : "text-(--t-3)")}>
            {typeof aioScore === "number" ? Math.round(aioScore) : "N/A"}
          </span>
          <span className="text-xs font-black text-(--t-3)">/100</span>
        </div>
      </header>

      {searchTypes.length > 0 && (
        <div className="space-y-6">
          <div className="flex items-center gap-3">
            <Sparkles className="h-3.5 w-3.5 text-primary" />
            <span className="text-[10px] font-black uppercase tracking-[0.2em] text-(--t-2)">
              Search types
            </span>
            <div className="h-px flex-1 bg-(--line-2)" />
          </div>
          <SearchTypeCards
            searchTypes={searchTypes}
            canSeeComparison={canSeeComparison}
            guestAuditToken={guestAuditToken}
          />
        </div>
      )}

      <div className="space-y-6">
        <div className="flex items-center gap-3">
          <Sparkles className="h-3.5 w-3.5 text-primary" />
          <span className="text-[10px] font-black uppercase tracking-[0.2em] text-(--t-2)">
            AI answers readiness
          </span>
          <div className="h-px flex-1 bg-(--line-2)" />
        </div>
        {aeoPanel}
      </div>

      <div className="space-y-6">
        <div className="flex items-center gap-3">
          <GeoIcon className="h-3.5 w-3.5 text-primary" />
          <span className="text-[10px] font-black uppercase tracking-[0.2em] text-(--t-2)">
            AI visibility
          </span>
          <div className="h-px flex-1 bg-(--line-2)" />
        </div>
        {geoPanel}
      </div>
    </section>
  );
}
