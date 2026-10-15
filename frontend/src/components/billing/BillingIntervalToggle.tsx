"use client";

import React from "react";

import { cx } from "@/components/ui/utils";
import type { BillingInterval } from "@/types/billing";

export default function BillingIntervalToggle({
  value,
  onChange,
}: {
  value: BillingInterval;
  onChange: (interval: BillingInterval) => void;
}) {
  const isAnnual = value === "year";

  return (
    <div className="flex min-w-0 flex-col items-center">
      {/* Segmented pill container */}
      <div className="relative flex max-w-full rounded-full border-0 bg-(--line-2) p-1 backdrop-blur-xs">
        {/* Sliding indicator */}
        <div
          aria-hidden="true"
          className={cx(
            "absolute top-1 bottom-1 rounded-full transition-all duration-300 ease-in-out",
            "bg-linear-to-r from-indigo-500 to-indigo-600 shadow-[0_1px_8px_rgba(99,102,241,0.35)]",
            isAnnual ? "left-[calc(50%+2px)] right-1" : "left-1 right-[calc(50%+2px)]"
          )}
        />

        <button
          type="button"
          aria-pressed={!isAnnual}
          onClick={() => onChange("month")}
          className={cx(
            "relative z-10 rounded-full px-3 py-1.5 text-[13px] font-semibold tracking-wide transition-colors duration-200 sm:px-6",
            !isAnnual ? "text-(--t-1)" : "text-slate-600 hover:text-slate-900"
          )}
        >
          Monthly
        </button>
        <button
          type="button"
          aria-pressed={isAnnual}
          onClick={() => onChange("year")}
          className={cx(
            "relative z-10 rounded-full px-3 py-1.5 text-[13px] font-semibold tracking-wide transition-colors duration-200 sm:px-6",
            isAnnual ? "text-(--t-1)" : "text-slate-600 hover:text-slate-900"
          )}
        >
          Annual
        </button>
      </div>

      {/* Discount disclaimer below the toggle */}
      <p
        className={cx(
          "mt-2 text-center text-[11px] tracking-wide transition-colors duration-200",
          isAnnual ? "text-emerald-400" : "text-(--muted-foreground)"
        )}
      >
        Save 20% with annual billing
      </p>
    </div>
  );
}
