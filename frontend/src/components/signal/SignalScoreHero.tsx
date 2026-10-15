"use client";

import React from "react";

import SignalScoreRing from "@/components/signal/SignalScoreRing";
import { cx } from "@/components/ui/utils";

export type SignalScoreHeroProps = {
  score: number | null;
  eyebrow: string;
  title: string;
  copy: React.ReactNode;
  currentScoreLabel: string;
  targetLine: React.ReactNode;
  emptyLabel?: React.ReactNode;
  className?: string;
  color?: string;
};

/**
 * Compact score hero for AIO / SEO detail — ring (number only), title block,
 * and a dense current-score chip. No nested card frames, no /100 in the ring.
 */
export default function SignalScoreHero({
  score,
  eyebrow,
  title,
  copy,
  currentScoreLabel,
  targetLine,
  emptyLabel,
  className,
  color = "#3B82F6",
}: SignalScoreHeroProps) {
  const pct = score === null ? 0 : Math.max(0, Math.min(100, score));

  return (
    <div
      className={cx(
        "relative overflow-hidden rounded-[18px] border-0 bg-[#F4F7FB]",
        className
      )}
      data-score-hero
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-y-0 left-0 w-[42%] bg-[radial-gradient(ellipse_at_20%_50%,rgba(59,130,246,0.14)_0%,transparent_70%)]"
      />
      <div className="relative flex items-center gap-3.5 px-4 py-3 max-md:flex-col max-md:items-stretch max-md:gap-3 max-md:p-3.5">
        <SignalScoreRing
          score={score}
          size={78}
          label={null}
          color={color}
          trackColor="#E2E8F0"
          centerBg="#FFFFFF"
          valueClassName="text-[22px]!"
          className="max-md:self-center"
          emptyLabel={emptyLabel}
        />

        <div className="min-w-0 flex-1">
          <span className="inline-flex rounded-full bg-white px-2 py-px text-[10px] font-semibold text-[#1D4ED8] shadow-[0_0_0_1px_rgba(29,78,216,0.12)]">
            {eyebrow}
          </span>
          <h1 className="mt-1 mb-0.5 font-(family-name:--disp) text-[18px] font-extrabold leading-[1.25] tracking-[-0.02em] text-[#111827]">
            {title}
          </h1>
          <p className="m-0 max-w-[540px] text-[12.5px] leading-[1.4] text-(--t-2)">{copy}</p>
        </div>

        <div className="flex w-[168px] flex-none flex-col justify-center rounded-[14px] bg-white px-3.5 py-2.5 shadow-[0_0_0_1px_rgba(17,24,39,0.05)] max-md:w-full">
          <div className="flex items-end justify-between gap-2">
            <div className="text-[9.5px] font-semibold uppercase tracking-[0.07em] text-(--t-3)">
              {currentScoreLabel}
            </div>
            <div className="flex items-baseline gap-0.5 leading-none">
              <span className="font-(family-name:--disp) text-[22px] font-extrabold tracking-[-0.03em] text-[#111827]">
                {score === null ? (
                  <span className="font-(family-name:--body-font) text-[11px] font-semibold tracking-normal text-(--t-3)">
                    {emptyLabel ?? "—"}
                  </span>
                ) : (
                  score
                )}
              </span>
              {score !== null ? (
                <span className="text-[10px] font-semibold text-(--t-3)">/100</span>
              ) : null}
            </div>
          </div>
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-[#EEF1F6]">
            <i
              className="block h-full rounded-full"
              style={{ width: `${pct}%`, backgroundColor: color }}
              data-signal-enter="bar"
            />
          </div>
          <div className="mt-1.5 text-[11px] leading-[1.3] text-(--t-3)">{targetLine}</div>
        </div>
      </div>
    </div>
  );
}
