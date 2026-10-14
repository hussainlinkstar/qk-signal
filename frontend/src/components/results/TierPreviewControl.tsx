"use client";

import React from "react";
import { cx } from "@/components/ui/utils";
import type { CanonicalPlanType } from "@/lib/planCapabilities";

/**
 * Non-prod QA control for previewing the value-ladder blur/unlock states
 * (Phase 5, Task 5.3).
 *
 * This control is a *visual preview only*. It NEVER changes real entitlements
 * and is NOT wired into any server call: selecting a tier simply swaps the
 * `canSee*` booleans the report passes down to its panels so QA can eyeball the
 * blurred upsell teasers per tier. Real audits stay server-enforced.
 *
 * It mounts ONLY when `NEXT_PUBLIC_ENABLE_TIER_PREVIEW === "true"` (a non-prod
 * flag). With the flag off — i.e. production — the component renders nothing.
 */
export const TIER_PREVIEW_ENABLED = process.env.NEXT_PUBLIC_ENABLE_TIER_PREVIEW === "true";

type PreviewTier = {
  label: string;
  planKey: CanonicalPlanType;
};

// Ordered low → high to mirror the value ladder (Free → Executive).
const PREVIEW_TIERS: readonly PreviewTier[] = [
  { label: "Free", planKey: "plan_starter" },
  { label: "Standard", planKey: "plan_standard" },
  { label: "Specialist", planKey: "plan_specialist" },
  { label: "Executive", planKey: "plan_executive" },
] as const;

type TierPreviewControlProps = {
  /** Currently previewed plan key, or `null` when showing real entitlements. */
  value: string | null;
  /**
   * Called when the QA operator picks a tier (a plan key) or returns to the
   * real entitlements view (`null`).
   */
  onPreviewTier: (planKey: string | null) => void;
};

export default function TierPreviewControl({ value, onPreviewTier }: TierPreviewControlProps) {
  // Hard gate: render nothing unless the non-prod preview flag is on.
  if (!TIER_PREVIEW_ENABLED) {
    return null;
  }

  return (
    <div
      data-testid="tier-preview-control"
      className="flex flex-wrap items-center gap-2 rounded border border-amber-500/30 bg-amber-500/5 px-3 py-2"
    >
      <span className="text-[10px] font-black uppercase tracking-[0.2em] text-amber-400/90">
        QA · Preview plan
      </span>
      <div className="inline-flex items-center gap-1 rounded bg-black/30 p-1">
        <button
          type="button"
          data-testid="tier-preview-live"
          aria-pressed={value === null}
          onClick={() => onPreviewTier(null)}
          className={cx(
            "rounded px-2.5 py-1 text-[11px] font-bold uppercase tracking-widest transition-colors",
            value === null ? "bg-(--line-2) text-(--t-1)" : "text-(--t-2) hover:text-(--t-1)"
          )}
        >
          Live
        </button>
        {PREVIEW_TIERS.map((tier) => (
          <button
            key={tier.planKey}
            type="button"
            data-testid={`tier-preview-${tier.planKey}`}
            aria-pressed={value === tier.planKey}
            onClick={() => onPreviewTier(tier.planKey)}
            className={cx(
              "rounded px-2.5 py-1 text-[11px] font-bold uppercase tracking-widest transition-colors",
              value === tier.planKey
                ? "bg-(--line-2) text-(--t-1)"
                : "text-(--t-2) hover:text-(--t-1)"
            )}
          >
            {tier.label}
          </button>
        ))}
      </div>
      <span className="text-[9px] font-bold uppercase tracking-widest text-amber-400/60">
        Visual only · real audits stay gated
      </span>
    </div>
  );
}
