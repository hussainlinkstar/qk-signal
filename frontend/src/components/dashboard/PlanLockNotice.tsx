import Link from "next/link";
import React from "react";
import { ArrowRight } from "lucide-react";
import { cx } from "@/components/ui/utils";
import type { PlanLockContent } from "@/lib/planLocks";

type PlanLockNoticeProps = PlanLockContent & {
  className?: string;
  badgeLabel?: string;
  align?: "left" | "center";
};

// signal-MVP `.lockcard`: centred 380px panel card, mono purple plan eyebrow,
// Satoshi 18/800 title, 13px body, full-width `.btn.pri` CTA. No demo unlock -
// entitlement is server-enforced, so there is no client-side reveal control.
export default function PlanLockNotice({
  requiredPlanLabel,
  title,
  description,
  ctaLabel,
  href,
  className,
  badgeLabel,
}: PlanLockNoticeProps) {
  return (
    <section
      className={cx(
        "mx-auto w-full max-w-[380px] rounded-[22px] border-0 bg-white px-6 py-[22px] text-center shadow-[0_24px_60px_-24px_rgba(12,15,22,0.4)]",
        className
      )}
    >
      <div className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.14em] text-(--purple)">
        {requiredPlanLabel}
      </div>
      {badgeLabel ? <div className="mt-1 text-[11px] text-(--t-3)">{badgeLabel}</div> : null}
      <h2 className="mx-0 mb-1.5 mt-2 font-(family-name:--disp) text-[18px] font-extrabold tracking-[-0.02em] text-(--t-1)">
        {title}
      </h2>
      <p className="mb-4 text-[13px] leading-[1.5] text-(--t-2)">{description}</p>
      <Link
        href={href}
        className="inline-flex h-[38px] w-full items-center justify-center gap-2 rounded-[10px] bg-(--ink) px-[15px] text-[13.5px] font-semibold text-white transition-colors hover:bg-black focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple) focus-visible:ring-offset-2 max-md:min-h-11"
      >
        {ctaLabel}
        <ArrowRight className="h-4 w-4 rtl:rotate-180" aria-hidden="true" />
      </Link>
    </section>
  );
}
