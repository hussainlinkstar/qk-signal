"use client";

import React from "react";
import { cx } from "@/components/ui/utils";

export type SignalScoreRingProps = {
  /** 0–100 progress; null renders the empty track + unmeasured label. */
  score: number | null;
  /** Center pill label — defaults to "/100". */
  label?: string;
  /** Outer box size in px. */
  size?: number;
  /** Progress stroke color. */
  color?: string;
  /** Soft track color behind the progress arc. */
  trackColor?: string;
  /** Soft disc behind the center metric. */
  centerBg?: string;
  /** Optional unmeasured center copy when score is null. */
  emptyLabel?: React.ReactNode;
  className?: string;
  valueClassName?: string;
  /** Entrance hooks used by signal chart motion. */
  enterAttrs?: {
    value?: Record<string, string | number | undefined>;
    ring?: Record<string, string | number | undefined>;
  };
};

/**
 * Stylish flat score ring — soft center disc, bold metric, pill label,
 * rounded stroke caps. Matches the Channel Mix donut center treatment.
 */
export default function SignalScoreRing({
  score,
  label = "/100",
  size = 132,
  color = "#3B82F6",
  trackColor = "#EEF1F6",
  centerBg = "#F8FAFC",
  emptyLabel,
  className,
  valueClassName,
  enterAttrs,
}: SignalScoreRingProps) {
  const stroke = Math.max(8, Math.round(size * 0.083));
  const vb = 120;
  const r = 50;
  const c = 2 * Math.PI * r;
  const pct = score === null ? 0 : Math.max(0, Math.min(100, score));
  const valueSize =
    size >= 130 ? "text-[34px]" : size >= 100 ? "text-[28px]" : size >= 72 ? "text-[17px]" : "text-[13px]";
  const pillSize = size >= 100 ? "text-[11px] px-2 py-0.5" : "text-[9px] px-1.5 py-px";
  const centerInset = size >= 100 ? "inset-[20%]" : "inset-[18%]";

  return (
    <div
      className={cx("relative flex-none", className)}
      style={{ width: size, height: size }}
      data-score-ring
    >
      <svg viewBox={`0 0 ${vb} ${vb}`} className="h-full w-full -rotate-90" aria-hidden="true">
        <circle cx={vb / 2} cy={vb / 2} r={r} fill="none" stroke={trackColor} strokeWidth={stroke} />
        <circle
          cx={vb / 2}
          cy={vb / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - pct / 100)}
          data-signal-enter="ring"
          {...enterAttrs?.ring}
        />
      </svg>
      <div
        className={cx(
          "absolute flex flex-col items-center justify-center rounded-full",
          centerInset
        )}
        style={{ backgroundColor: centerBg }}
      >
        <b
          className={cx(
            "font-(family-name:--disp) font-extrabold leading-none tracking-[-0.03em] text-[#111827]",
            valueSize,
            valueClassName
          )}
          data-signal-enter="count"
          data-signal-count={score ?? undefined}
          {...enterAttrs?.value}
        >
          {score === null
            ? (emptyLabel ?? (
                <span className="font-(family-name:--body-font) text-[11px] font-semibold tracking-normal text-(--t-3)">
                  —
                </span>
              ))
            : Math.round(score)}
        </b>
        {score !== null ? (
          <small
            className={cx(
              "mt-1.5 rounded-full bg-white font-semibold text-(--t-3)",
              pillSize
            )}
          >
            {label}
          </small>
        ) : null}
      </div>
    </div>
  );
}
