import React from "react";

import { cx } from "./utils";

type SignalLoaderProps = {
  /** Uppercase mono caption under the ring. */
  label?: string;
  /** Optional secondary line. */
  detail?: string;
  /** `inline` shrinks the vertical footprint for in-page/section loads. */
  inline?: boolean;
  className?: string;
};

/**
 * The single Signal loading indicator (signal-MVP line): a thin gradient ring
 * + mono caption. Replaces the legacy "Intelligence Engine" synapse animation
 * and lucide spinners so page and section loads look consistent and on-brand.
 */
export function SignalLoader({
  label = "Loading",
  detail,
  inline = false,
  className,
}: SignalLoaderProps) {
  return (
    <div
      className={cx(
        "flex min-h-[52vh] flex-col items-center justify-center gap-[15px] px-5 py-10",
        inline && "min-h-0 px-5 py-8",
        className
      )}
      role="status"
      aria-live="polite"
      aria-label={label}
    >
      <span
        className="h-[34px] w-[34px] animate-sg-spin rounded-[50%] bg-[conic-gradient(from_90deg,#2563eb,#9333ea,rgba(147,51,234,0))] [mask:radial-gradient(farthest-side,transparent_calc(100%-3.5px),#000_calc(100%-3.5px))]"
        aria-hidden="true"
      />
      <span className="font-(family-name:--font-roboto-mono) text-[11px] uppercase tracking-[0.14em] text-(--t-3)">
        {label}
      </span>
      {detail ? (
        <span className="mt-[-8px] font-(family-name:--font-sans) text-[12.5px] text-(--t-2)">
          {detail}
        </span>
      ) : null}
    </div>
  );
}

export default SignalLoader;
