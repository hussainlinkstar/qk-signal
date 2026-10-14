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
 * Matches signal-MVP's `.hero`: gauge (`.gwrap`) + meta (`.hmeta`: eyebrow/h1/p)
 * + optional path-to-target card (`.gap`). (signal.css lines 49-64)
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
    <div className="relative flex flex-col min-w-0 gap-5 overflow-hidden rounded-[16px] border border-(--line) bg-(--panel) p-5 md:flex-row md:items-center md:gap-[26px] md:p-[24px_28px]">
      <span
        className={cx(
          "absolute inset-y-0 start-0 w-1",
          accent === "gradient" ? "bg-(image:--grad)" : "bg-(--blue)"
        )}
        aria-hidden="true"
      />
      <div className="self-center flex-none md:self-auto">
        <SignalGauge score={score} size={132} />
      </div>
      <div className="min-w-0 flex-1">
        <div
          className={cx(
            "font-(family-name:--mono) text-[11px] uppercase tracking-[0.14em]",
            accent === "gradient" ? "text-(--purple)" : "text-(--blue)"
          )}
        >
          {eyebrow}
        </div>
        <h1 className="my-[8px] mb-1.5 font-(family-name:--disp) text-[28px] font-black tracking-[-0.02em] text-(--t-1)">
          {title}
        </h1>
        <p className="text-[13.5px] leading-[1.55] text-(--t-2)">{description}</p>
      </div>
      {target && (
        <div className="w-full flex-none rounded-xl border border-(--line) bg-(--paper) p-[16px_18px] md:w-[250px]">
          <div className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
            Path to target
          </div>
          <div className="my-2 mb-1 flex items-baseline gap-2">
            <span className="font-(family-name:--disp) text-[30px] font-black tracking-[-0.02em] text-(--t-1)">
              {target.now}
            </span>
            <span className="text-(--t-3)">→</span>
            <span
              className={cx(
                "font-(family-name:--disp) text-[22px] font-extrabold",
                accent === "gradient" ? "text-(--purple)" : "text-(--blue)"
              )}
            >
              {target.target}
            </span>
          </div>
          <div className="text-[12.5px] text-(--t-2)">{target.note}</div>
        </div>
      )}
    </div>
  );
}
