"use client";

import React from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import SignalStatusShell from "@/components/signal/SignalStatusShell";

/**
 * Approved `Signal 404.html`: the full app shell around the not-found card —
 * gradient 404, the approved reason line, a "Search everything ⌘K" button
 * opening the shell palette, and quick links to the useful places. The
 * mockup's project-scoped links (AIO score, Competitors) only make sense
 * inside a project, which a 404 cannot know, so the row keeps the
 * workspace-resolvable destinations: Dashboard, Reports, Settings.
 */
const QUICK_LINKS = [
  { nameKey: "nav.dashboard", href: "/dashboard" },
  { nameKey: "nav.reports", href: "/dashboard/reports" },
  { nameKey: "nav.settings", href: "/dashboard/settings" },
] as const;

export default function SignalNotFound() {
  const { t } = useTranslation();

  return (
    <SignalStatusShell crumb={t("notFound.page.crumb")}>
      {(openPalette) => (
        /* `.card.sblock` + inline styles from Signal 404.html: max-width 600
           (shrink-to-fit inside the flex wrap), margin 40 auto, padding
           20px 22px, centred. */
        <div className="mx-auto my-10 w-fit max-w-[600px] rounded-[22px] border-0 bg-white px-[22px] py-5 text-center">
          <div className="bg-(image:--grad) bg-clip-text font-(family-name:--disp) text-[54px] font-black leading-[1.35] tracking-[-0.02em] text-transparent">
            404
          </div>
          {/* `.sblock h3` + inline 18px: disp, 700, margin 0 0 3px. */}
          <h1 className="mb-[3px] font-(family-name:--disp) text-[18px] font-bold leading-6 text-(--t-1)">
            {t("notFound.page.title")}
          </h1>
          {/* `.sd` + inline margin 6px 0 14px. */}
          <p className="mt-1.5 mb-3.5 text-[12.5px] leading-[15px] text-(--t-3)">
            {t("notFound.page.description")}
          </p>
          {/* `.btn.pri` + inline margin 0 auto 18px: h38, pad 0 15, ink fill,
              13.5px/600, 16px icon, `.ts-hint` kbd chip. */}
          <button
            type="button"
            onClick={openPalette}
            className="mx-auto mb-[18px] inline-flex h-[38px] items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] text-[13.5px] font-semibold leading-[1.2] text-white transition-colors hover:bg-black focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple)"
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              width="16"
              height="16"
              strokeWidth="2"
              aria-hidden="true"
            >
              <circle cx="11" cy="11" r="7" />
              <path d="M21 21l-4.3-4.3" />
            </svg>
            {t("notFound.page.search")}
            <kbd className="ms-2 flex-none rounded-[5px] border-0 bg-white px-1.5 py-px font-(family-name:--mono) text-[10px] text-(--t-3)">
              ⌘K
            </kbd>
          </button>
          {/* `.sd` + inline margin-bottom 10px. */}
          <p className="mb-2.5 text-[12.5px] leading-[15px] text-(--t-3)">
            {t("notFound.page.quickLinks")}
          </p>
          {/* `.cmp-row` of `.btn.sm`: h30, pad 0 11, 12px/600 t-1, r-sm 8px. */}
          <div className="flex flex-wrap items-center justify-center gap-2.5">
            {QUICK_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="inline-flex h-[30px] items-center rounded-[8px] border-0 bg-white px-[11px] text-xs font-semibold text-(--t-1) transition-colors hover:bg-[#E8ECF3] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple)"
              >
                {t(link.nameKey)}
              </Link>
            ))}
          </div>
        </div>
      )}
    </SignalStatusShell>
  );
}
