"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { Trans, useTranslation } from "react-i18next";
import { asset } from "@/lib/basePath";
import SignalStatusShell from "@/components/signal/SignalStatusShell";

/**
 * Approved `Signal Maintenance.html`: the full app shell around a single
 * light card. The page must work while the API is down, so nothing here
 * waits on a data fetch — the shell renders the static workspace IA and the
 * switcher degrades to its empty state. The health probe below is the same
 * behaviour the old standalone page had: once the backend stops answering
 * 503 the user is sent home.
 */
export default function MaintenancePage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<{ message?: string; retry_after?: number } | null>(null);

  useEffect(() => {
    fetch("/api/system-status/health")
      .then((res) => {
        if (res.status === 503) {
          return res.json();
        }
        if (res.status === 200) {
          window.location.href = asset("/");
        }
        return null;
      })
      .then((data) => {
        if (data) setStatus(data);
      })
      .catch(() => {});
  }, []);

  const rows: { label: string; state: string; available: boolean }[] = [
    { label: t("maintenance.rowNewScans"), state: t("maintenance.statePaused"), available: false },
    {
      label: t("maintenance.rowReports"),
      state: t("maintenance.stateAvailable"),
      available: true,
    },
    {
      label: t("maintenance.rowDashboard"),
      state: t("maintenance.stateAvailableReadonly"),
      available: true,
    },
  ];

  return (
    <SignalStatusShell crumb={t("maintenance.crumb")}>
      {/* `.card.sblock` + inline styles from Signal Maintenance.html:
          max-width 560, margin 60 auto, sblock padding 20px 22px. */}
      <div className="mx-auto my-[60px] w-fit max-w-[560px] rounded-[16px] border border-(--line) bg-(--panel) px-[22px] py-5 text-center">
        {/* Approved glyph is the amber warning triangle at the decorative
            stroke colour #D9930B on rgba(217,147,11,.12); like the gauge
            strokes it is decorative, so it keeps the approved value rather
            than the accessible --warn text colour. */}
        <div className="mx-auto mb-3.5 flex h-[52px] w-[52px] items-center justify-center rounded-full bg-[rgba(217,147,11,0.12)] text-[#D9930B]">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="24" aria-hidden="true">
            <path d="M12 4l9 16H3z" strokeLinejoin="round" />
            <path d="M12 10v4M12 17h.01" strokeLinecap="round" />
          </svg>
        </div>
        {/* `.sblock h3` + inline 18px: disp, 700, margin 0 0 3px. */}
        <h1 className="mb-[3px] font-(family-name:--disp) text-[18px] font-bold leading-6 text-(--t-1)">
          {t("maintenance.title")}
        </h1>
        {/* `.sd` + inline margin 6px 0 14px. */}
        <p className="mt-1.5 mb-3.5 text-[12.5px] leading-[15px] text-(--t-3)">
          {status?.message || t("maintenance.description")}
        </p>
        {/* `.wtable`: td padding 13px 16px, 13px, --line-2 row rules; the
            value cell is `.yes`/`.no` (mono 12px) in normal cell flow. */}
        <table className="mb-4 w-full border-collapse text-start">
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className="border-b border-(--line-2) last:border-b-0">
                <td className="px-4 py-[13px] align-middle text-[13px] leading-[1.35] text-(--t-1)">
                  {row.label}
                </td>
                <td
                  className={
                    row.available
                      ? "px-4 py-[13px] align-middle font-(family-name:--mono) text-xs leading-[1.35] text-(--good)"
                      : "px-4 py-[13px] align-middle font-(family-name:--mono) text-xs leading-[1.35] text-(--bad)"
                  }
                >
                  {row.state}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {/* `.wnote` is a <p>: 12px --t-3 with the UA 1em (12px) margins. */}
        <p className="my-3 text-xs leading-[15px] text-(--t-3)">
          <Trans
            i18nKey="maintenance.note"
            components={{
              1: (
                // eslint-disable-next-line react/jsx-no-target-blank
                <a
                  href="https://qiko.ai"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-inherit"
                />
              ),
            }}
          />
        </p>
        {/* `.btn` + inline margin-top 8px: h38, pad 0 15, radius --r-md,
            13.5px/600, hover darkens the border only. */}
        <Link
          href="/dashboard"
          className="mt-2 inline-flex h-[38px] items-center justify-center gap-2 rounded-[10px] border border-(--line) bg-(--panel) px-[15px] text-[13.5px] font-semibold leading-[1.2] text-(--t-1) transition-colors hover:border-[#D7DAE0] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple)"
        >
          {t("maintenance.back")}
        </Link>
      </div>
    </SignalStatusShell>
  );
}
