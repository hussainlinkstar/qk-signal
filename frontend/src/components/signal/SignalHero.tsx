"use client";

import { cx } from "@/components/ui/utils";
import SignalGauge from "@/components/signal/SignalGauge";

export type SignalHeroProps = {
  score: number;
  eyebrow: string;
  title: string;
  description: string;
  /** Accent for the eyebrow + AIO gradient bar. */
  accent?: "blue" | "gradient";
  /** Path-to-target card (right side). Omit to hide. */
  target?: { now: number; target: number; note: React.ReactNode };
};

/**
 * Flat hero block used across project/module screens.
 */
export default function SignalHero({
  score,
  eyebrow,
  title,
  description,
  accent = "blue",
  target,
}: SignalHeroProps) {
  return (
    <div className="relative flex flex-col min-w-0 gap-5 overflow-hidden rounded-[22px] border-0 bg-white p-5 md:flex-row md:items-center md:gap-[26px] md:p-6">
      <div className="self-center flex-none md:self-auto">
        <SignalGauge score={score} size={132} />
      </div>
      <div className="min-w-0 flex-1">
        <div
          className={cx(
            "text-[11px] font-semibold uppercase tracking-[0.12em]",
            accent === "gradient" ? "text-[#7C3AED]" : "text-[#2563EB]"
          )}
        >
          {eyebrow}
        </div>
        <h1 className="my-2 mb-1.5 font-(family-name:--disp) text-[28px] font-bold tracking-[-0.03em] text-[#111827]">
          {title}
        </h1>
        <p className="text-[14px] leading-[1.55] text-[#6B7280]">{description}</p>
      </div>
      {target && (
        <div className="w-full flex-none rounded-[16px] border-0 bg-[#F7F8FA] p-4 md:w-[250px]">
          <div className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-[#9CA3AF]">
            Path to target
          </div>
          <div className="my-2 mb-1 flex items-baseline gap-2">
            <span className="font-(family-name:--disp) text-[30px] font-bold tracking-[-0.02em] text-[#111827]">
              {target.now}
            </span>
            <span className="text-[#9CA3AF]">→</span>
            <span
              className={cx(
                "font-(family-name:--disp) text-[22px] font-bold",
                accent === "gradient" ? "text-[#7C3AED]" : "text-[#2563EB]"
              )}
            >
              {target.target}
            </span>
          </div>
          <div className="text-[12.5px] text-[#6B7280]">{target.note}</div>
        </div>
      )}
    </div>
  );
}
