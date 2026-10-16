"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";

import { cx } from "@/components/ui/utils";

type AuditStickyStartBarProps = {
  planLabel: string;
  remaining: number | null | undefined;
  isStartDisabled: boolean;
  startLabel: string;
  isBusy: boolean;
};

/**
 * Bottom-pinned start bar (UI/UX Fixes): allowance on the left, Start on the
 * right — so users finishing the left column never hunt for the launch card.
 */
export default function AuditStickyStartBar({
  planLabel,
  remaining,
  isStartDisabled,
  startLabel,
  isBusy,
}: AuditStickyStartBarProps) {
  const { t } = useTranslation();
  const isUnlimited = remaining === null;

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-40 px-3 pb-3 md:px-6 md:pb-4">
      <div className="pointer-events-auto mx-auto flex w-full max-w-[1100px] flex-wrap items-center justify-between gap-3 rounded-[18px] border border-(--line) bg-white/95 px-4 py-3 shadow-[0_12px_40px_-16px_rgba(88,28,135,0.28)] backdrop-blur-md">
        <div className="min-w-0">
          <p className="m-0 text-[11px] font-semibold uppercase tracking-[0.06em] text-(--purple-deep,var(--purple))">
            {t("signalStartCheck.allowance.heading")}
          </p>
          <p className="m-0 mt-0.5 truncate text-[13.5px] font-semibold text-(--t-1)">
            {isUnlimited
              ? t("signalStartCheck.allowance.planLineUnlimited", { plan: planLabel })
              : typeof remaining === "number"
                ? t("signalStartCheck.allowance.remaining", {
                    remaining: remaining.toLocaleString(),
                  })
                : t("signalStartCheck.allowance.unknown")}
          </p>
        </div>
        <button
          type="submit"
          disabled={isStartDisabled}
          className={cx(
            "inline-flex h-[38px] min-w-[10.5rem] cursor-pointer items-center justify-center gap-2 rounded-full border-0 px-5 font-(family-name:--body-font) text-[13.5px] font-semibold transition-colors duration-150",
            !isStartDisabled
              ? "bg-(--purple) text-white shadow-[0_10px_22px_-12px_color-mix(in_srgb,var(--purple)_55%,transparent)] hover:brightness-105"
              : "cursor-not-allowed bg-(--well,#EEF1F6) text-(--t-3)"
          )}
        >
          {isBusy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
          {startLabel}
        </button>
      </div>
    </div>
  );
}
