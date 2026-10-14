"use client";

import React from "react";
import Link from "next/link";
import { ArrowRight, Lock, Sparkles, Zap } from "lucide-react";

import { buttonClasses } from "@/components/ui/Button";
import { cx } from "@/components/ui/utils";
import { resolvePlanType } from "@/lib/planCapabilities";

type GatedSectionProps = {
  title: string;
  /**
   * Accepted for call-site compatibility but intentionally not rendered.
   *
   * The previous layout stacked a `blur-[3px] opacity-40` preview under a
   * radial vignette that reached full `--surface` at 70% plus another 60%
   * surface wash. Together those erased the preview, so a wide section
   * rendered as two blank panels flanking the centred upsell card and read as
   * a broken, cut-in-half layout rather than a teaser. A self-contained panel
   * is honest about the section being locked and survives any section width.
   */
  blurredPreview?: React.ReactNode;
  teaser: string;
  requiredPlan?: string;
  /**
   * The plan that unlocks this section. Omit it when the section is not
   * withheld by plan at all - a guest gate withholds the whole tab from
   * anyone who has not signed up, and free Starter unlocks it, so naming a
   * paid plan there would be a price on something that costs nothing.
   */
  requiredPlanLabel?: string;
  guestAuditToken?: string;
  className?: string;
  /**
   * Bullets describing what unlocking THIS specific section gets you.
   * Callers should tailor these to the gated feature; falls back to a
   * generic list only when a caller hasn't supplied its own (kept so every
   * upsell card doesn't read as an identical, templated placeholder).
   */
  features?: string[];
};

const DEFAULT_FEATURES = [
  "Full findings & deep analysis",
  "Actionable implementation steps",
  "Score tracking across audits",
];

const BILLING_PLANS_HREF = "/dashboard/billing?section=plans";

export default function GatedSection({
  title,
  teaser,
  requiredPlan,
  requiredPlanLabel,
  guestAuditToken,
  className,
  features = DEFAULT_FEATURES,
}: GatedSectionProps) {
  /**
   * SIGV2-1221: who is being asked to do what.
   *
   * This card used to render one CTA for everybody: "Start Free, Unlock Full
   * Report" linking to `/register`. That is the right ask for a guest reading
   * a shared audit, and the wrong one for every other caller - a signed-in
   * Standard customer looking at an Executive-gated section was told to start
   * a free account they already have, on a page that could not unlock
   * anything. The plan the card names was computed and then thrown away.
   *
   * A guest audit token is the only thing that identifies the guest flow, so
   * it is what selects the CTA. Everyone else gets the upgrade the card is
   * actually about, deep-linked to the plan it names through the shared alias
   * table rather than a hand-built query parameter.
   */
  const isGuest = Boolean(guestAuditToken);
  const canonicalPlan = resolvePlanType(requiredPlan);
  const ctaHref = isGuest
    ? `/register?guest_audit_token=${encodeURIComponent(guestAuditToken as string)}`
    : canonicalPlan
      ? `${BILLING_PLANS_HREF}&plan=${canonicalPlan}`
      : BILLING_PLANS_HREF;
  const ctaLabel = isGuest
    ? "Start Free, Unlock Full Report"
    : requiredPlanLabel
      ? `Upgrade to ${requiredPlanLabel}`
      : "Upgrade your plan";

  return (
    <div
      className={cx(
        "rounded-xl border border-dashed border-(--line) bg-(--surface) p-6",
        className
      )}
    >
      <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
        <div className="flex min-w-0 items-start gap-4">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-primary/20 bg-primary/[0.08]">
            <Lock className="h-4 w-4 text-primary" />
          </span>

          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h3 className="text-base font-semibold tracking-tight text-(--foreground)">
                {title}
              </h3>
              {requiredPlanLabel ? (
                <span className="text-[10px] font-medium uppercase tracking-widest text-(--muted-foreground)">
                  Available on {requiredPlanLabel} and above
                </span>
              ) : null}
            </div>

            <p className="mt-1.5 text-sm leading-relaxed text-(--muted-foreground)">{teaser}</p>

            <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5">
              {features.map((feat) => (
                <li key={feat} className="flex items-center gap-2 text-xs text-(--text-soft)">
                  <Sparkles className="h-3 w-3 shrink-0 text-primary/70" />
                  {feat}
                </li>
              ))}
            </ul>
          </div>
        </div>

        <Link
          className={cx(
            buttonClasses({ variant: "primary", size: "md" }),
            "inline-flex shrink-0 gap-2"
          )}
          href={ctaHref}
        >
          <Zap className="h-4 w-4" />
          {ctaLabel}
          <ArrowRight className="h-4 w-4" />
        </Link>
      </div>
    </div>
  );
}
