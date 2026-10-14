"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import { formatDate } from "@/lib/dateFormatShared";
import { cx } from "@/components/ui/utils";

/**
 * The plan's scan allowance stated next to a rescan offer (SIGV2-1094).
 * `remaining` null means the plan is unlimited; nothing renders when no
 * allowance is known at all, so the line is never invented.
 *
 * SIGV2-1135: the window is the backend's, not a calendar month. The allowance
 * resets on a rolling 30 days measured from the oldest counted scan
 * (`services/scan_allowance_service.py`: SCAN_ALLOWANCE_WINDOW_DAYS = 30,
 * `reset_at` is that oldest scan plus the window), so "this month" was both
 * wrong and able to contradict the reset date printed beside it. A failed scan
 * is also counted - the service bills at job acceptance and says so, and on
 * Starter (`max_audits: 1`) that means one failure costs the whole window - so
 * the note states that rather than letting the customer discover it. Whether a
 * failure should be refunded is open on SIGV2-1119; nothing here promises one.
 */
export default function ScanAllowanceNote({
  used,
  remaining,
  resetAt,
  className,
}: {
  used?: number | null;
  remaining?: number | null;
  resetAt?: string | null;
  className?: string;
}) {
  const { t } = useTranslation();

  // undefined: the payload did not carry the field, so nothing is known and
  // nothing renders. null: the plan has no scan cap.
  if (remaining === undefined) {
    return null;
  }
  if (remaining === null) {
    if (used === null || used === undefined) {
      return null;
    }
    return (
      <span className={cx("text-[11.5px] text-(--t-3)", className)}>
        {t("signalScans.unlimited")}
      </span>
    );
  }

  const limit = typeof used === "number" ? used + remaining : null;
  const resetDate = resetAt ? formatDate(resetAt) : null;

  return (
    <span className={cx("text-[11.5px] text-(--t-3)", className)}>
      {limit !== null
        ? t("signalScans.leftOfLimit", { remaining, limit })
        : t("signalScans.left", { remaining })}
      {resetDate ? ` · ${t("signalScans.resetsOn", { date: resetDate })}` : ""}
      <span className="block">{t("signalScans.failedCount")}</span>
    </span>
  );
}
