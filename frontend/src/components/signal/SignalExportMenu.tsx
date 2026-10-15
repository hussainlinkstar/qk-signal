"use client";

import Link from "next/link";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { cx } from "@/components/ui/utils";
import { workspaceHeaders } from "@/components/app/WorkspaceSwitcher";
import { useAuth } from "@/components/auth/custom-auth";
import {
  downloadComplexReportPdfBlob,
  fetchComplexReportStatus,
  fetchReportExportVariants,
  generateComplexReportPdf,
  type ExportVariantEntitlement,
  type ExportVariantKey,
  type ReportKind,
} from "@/services/reportService";

/**
 * The Export control: `Signal Components.html` `.exp-menu` / `.exp-panel`,
 * wired by `Qiko-Signal-MVP-TBR/mockup/app.js` `wireExport`. Used from the
 * `.top` bar of the AIO detail, SEO detail and Competitors screens, exactly
 * where the approved pages put `<button data-export="...">Export</button>`.
 * The rows are the report kinds the product sells (SIGV2-1255), not the
 * mockup's branding tiers.
 *
 * Two things the mockup fakes and this does not:
 *
 *  - The lock. `app.js` reads a hard-coded `EXPORT_PLAN` constant. Here every
 *    variant takes its `locked` state from `GET /api/v1/reports/export-variants`,
 *    which resolves the same manifest and policy objects the enqueue endpoint
 *    enforces. A client-side table that drifted from the backend is the defect
 *    SIGV2-1108 had to fix, so there is deliberately none here.
 *  - The job states. `app.js` fires two timers to walk Queued -> Preparing ->
 *    Ready. Here each state is the job state the backend reports: `queued` is
 *    Queued, `running` is Preparing, `succeeded` is Ready, and `failed` /
 *    `expired` are the failure state. Nothing is animated forward on a timer,
 *    because the panel would then be describing a job nobody is watching.
 */

const POLL_DELAY_MS = 2000;
const MAX_POLL_ATTEMPTS = 45;

/**
 * The per-screen variant ordering. The menu sells report kinds, not branding
 * tiers (SIGV2-1255): Standard, Executive, AIO and SEO on every screen, with
 * the Competitors report first on the screen that measures them. The
 * membership itself is the backend's `EXPORT_VARIANT_SPECS` - a key the API
 * does not return simply does not render.
 */
export const EXPORT_MENU_PAGES: Record<string, ExportVariantKey[]> = {
  aio: ["standard", "executive", "aio", "seo"],
  seo: ["standard", "executive", "aio", "seo"],
  competitors: ["competitors", "standard", "executive", "aio", "seo"],
  report: ["standard", "executive", "aio", "seo"],
};

export type ExportMenuPage = keyof typeof EXPORT_MENU_PAGES;

/** The three states the approved design names, plus the failure it also draws. */
type JobState = "Queued" | "Preparing" | "Ready" | "Failed";

type Job = {
  variant: ExportVariantEntitlement;
  state: JobState;
  reportId: string | null;
  /** Set when the failure is "the file is gone", not "the build failed". */
  expired: boolean;
};

const LOCK_ICON = (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    aria-hidden="true"
    className="h-[13px] w-[13px] flex-none text-(--t-3)"
    strokeWidth={2}
  >
    <rect x="5" y="11" width="14" height="9" rx="2" />
    <path d="M8 11V7a4 4 0 0 1 8 0v4" />
  </svg>
);

/** Locked rows are not actionable, so the whole row carries one label. */
function lockedAriaLabel(name: string, locked: string, requirement: string): string {
  return `${name} - ${locked}, ${requirement}`;
}

export default function SignalExportMenu({
  page,
  auditId,
  projectId,
  reportKind,
  disabledReason,
  className,
}: {
  page: ExportMenuPage;
  /** The audit the export is built from. Null means there is nothing to export. */
  auditId: number | null;
  projectId?: number | null;
  /** The page's own report kind (`aio`, `seo`, `competitors`). */
  reportKind: ReportKind;
  /** Rendered as the button's title when the screen itself blocks export. */
  disabledReason?: string;
  className?: string;
}) {
  const { t } = useTranslation();
  const { getToken, isSignedIn } = useAuth();

  const [open, setOpen] = useState(false);
  const [variants, setVariants] = useState<ExportVariantEntitlement[] | null>(null);
  const [variantsError, setVariantsError] = useState(false);
  const [job, setJob] = useState<Job | null>(null);

  const wrapRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const itemRefs = useRef<(HTMLElement | null)[]>([]);
  // A job that is still polling must stop when the panel is dismissed, or the
  // next render would be driven by a job the customer already closed.
  const activeJobRef = useRef<string | null>(null);

  const authHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    return {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...workspaceHeaders(),
    };
  }, [getToken]);

  useEffect(() => {
    if (!isSignedIn) {
      setVariants(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const payload = await fetchReportExportVariants(await authHeaders());
        if (!cancelled) {
          setVariants(payload.variants);
          setVariantsError(false);
        }
      } catch {
        // Without the entitlement answer the menu cannot say what is locked, so
        // it says so rather than guessing and showing everything as available.
        if (!cancelled) {
          setVariants(null);
          setVariantsError(true);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [authHeaders, isSignedIn]);

  const rows = useMemo(() => {
    if (!variants) return [];
    const wanted = EXPORT_MENU_PAGES[page] ?? [];
    return wanted
      .map((key) => variants.find((variant) => variant.key === key))
      .filter((variant): variant is ExportVariantEntitlement => Boolean(variant));
  }, [page, variants]);

  const variantCopy = useCallback(
    (key: ExportVariantKey) => ({
      name: t(`signalExport.variants.${key}.name`),
      description: t(`signalExport.variants.${key}.description`),
    }),
    [t]
  );

  const closeMenu = useCallback((refocus = false) => {
    setOpen(false);
    if (refocus) buttonRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    const onDocumentClick = (event: MouseEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("click", onDocumentClick);
    return () => document.removeEventListener("click", onDocumentClick);
  }, [open]);

  const focusItem = useCallback((index: number) => {
    const list = itemRefs.current.filter(Boolean) as HTMLElement[];
    if (list.length === 0) return;
    const wrapped = ((index % list.length) + list.length) % list.length;
    list[wrapped]?.focus();
  }, []);

  const onButtonKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLButtonElement>) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setOpen(true);
        // The menu has to exist before the first row can take focus.
        window.requestAnimationFrame(() => focusItem(0));
      } else if (event.key === "Escape") {
        closeMenu();
      }
    },
    [closeMenu, focusItem]
  );

  const onMenuKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      const list = itemRefs.current.filter(Boolean) as HTMLElement[];
      const current = list.indexOf(document.activeElement as HTMLElement);
      if (event.key === "ArrowDown") {
        event.preventDefault();
        focusItem(current + 1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        focusItem(current - 1);
      } else if (event.key === "Escape" || event.key === "Tab") {
        closeMenu(true);
      }
    },
    [closeMenu, focusItem]
  );

  const runJob = useCallback(
    async (variant: ExportVariantEntitlement) => {
      if (auditId === null) return;
      const token = `${variant.key}:${Date.now()}`;
      activeJobRef.current = token;
      setJob({ variant, state: "Queued", reportId: null, expired: false });

      const fail = (expired = false) => {
        if (activeJobRef.current !== token) return;
        setJob((prev) => (prev ? { ...prev, state: "Failed", expired } : prev));
      };

      try {
        const headers = await authHeaders();
        const queued = await generateComplexReportPdf(
          {
            audit_ids: [auditId],
            project_id: typeof projectId === "number" ? projectId : undefined,
            template_type: variant.template_type,
            report_options: {
              mode: "individual",
              report_type: variant.report_type,
              report_kind: variant.report_kind ?? reportKind,
              branding_mode: "platform",
            },
          },
          headers
        );
        if (activeJobRef.current !== token) return;
        setJob((prev) =>
          prev
            ? {
                ...prev,
                reportId: queued.report_id,
                // The enqueue response already carries a real job state.
                state: queued.status === "running" ? "Preparing" : "Queued",
              }
            : prev
        );

        for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt += 1) {
          await new Promise((resolve) => setTimeout(resolve, POLL_DELAY_MS));
          if (activeJobRef.current !== token) return;
          const status = await fetchComplexReportStatus(queued.report_id, headers);
          if (activeJobRef.current !== token) return;
          if (status.status === "queued") {
            setJob((prev) => (prev ? { ...prev, state: "Queued" } : prev));
          } else if (status.status === "running") {
            setJob((prev) => (prev ? { ...prev, state: "Preparing" } : prev));
          } else if (status.status === "succeeded") {
            setJob((prev) => (prev ? { ...prev, state: "Ready" } : prev));
            return;
          } else {
            fail(status.status === "expired" || status.expired === true);
            return;
          }
        }
        // Still queued or running after the poll budget. The job may yet
        // finish, but this panel has stopped observing it, so it must not keep
        // claiming to. The report library is where the finished file shows up.
        fail();
      } catch {
        fail();
      }
    },
    [auditId, authHeaders, projectId, reportKind]
  );

  const downloadReady = useCallback(async () => {
    const reportId = job?.reportId;
    if (!reportId) return;
    try {
      const { blob, filename } = await downloadComplexReportPdfBlob(reportId, await authHeaders());
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename ?? `${reportKind}-report.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch {
      setJob((prev) => (prev ? { ...prev, state: "Failed", expired: false } : prev));
    }
  }, [authHeaders, job?.reportId, reportKind]);

  const dismissJob = useCallback(() => {
    activeJobRef.current = null;
    setJob(null);
  }, []);

  const buttonDisabled = auditId === null || variants === null;
  const buttonTitle =
    disabledReason ??
    (auditId === null
      ? t("signalExport.noAudit")
      : variantsError
        ? t("signalExport.unavailable")
        : undefined);

  return (
    // signal.css `.exp-wrap`: a positioning context for the menu and the job
    // panel, and nothing else. The approved `wireExport` inserts this same
    // wrapper around the button. `inline-flex` keeps it shrink-to-fit so the
    // button occupies the identical box it did as a bare flex item; the only
    // pixels that move are one grey level of antialiasing on its four rounded
    // corners, from the fractional layout position the extra box produces.
    <div ref={wrapRef} className={cx("relative inline-flex", className)}>
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={buttonDisabled}
        title={buttonTitle}
        onClick={(event) => {
          event.stopPropagation();
          setOpen((prev) => !prev);
        }}
        onKeyDown={onButtonKeyDown}
        className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3] disabled:cursor-not-allowed disabled:opacity-50"
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          aria-hidden="true"
          className="h-[15px] w-[15px]"
          strokeWidth={2}
          strokeLinecap="round"
        >
          <path d="M4 6h16M7 12h10M10 18h4" />
        </svg>
        {t("signalExport.button")}
      </button>

      {/* signal.css `.exp-menu` */}
      {open ? (
        <div
          role="menu"
          aria-label={t("signalExport.menuHeading")}
          onKeyDown={onMenuKeyDown}
          className="absolute top-[calc(100%+8px)] z-60 w-[296px] rounded-(--r-md) border-0 bg-white p-2 shadow-[0_16px_40px_-16px_rgba(12,15,22,0.28)] end-0"
        >
          <div className="px-2.5 pt-1.5 pb-2 font-(family-name:--disp) text-[13px] font-bold text-(--t-1)">
            {t("signalExport.menuHeading")}
          </div>
          {/* Every row is the same shape, because every variant is gated the
              same way: the `locked` flag the API serves, and nothing else.
              There is no second kind of row to keep in step. */}
          {rows.map((variant, index) => {
            const copy = variantCopy(variant.key);
            const requirement = variant.required_plan_label ?? t("signalExport.higherPlan");

            return (
              <button
                key={variant.key}
                ref={(node) => {
                  itemRefs.current[index] = node;
                }}
                type="button"
                role="menuitem"
                aria-disabled={variant.locked || undefined}
                aria-label={
                  variant.locked
                    ? lockedAriaLabel(copy.name, t("signalExport.locked"), requirement)
                    : undefined
                }
                onClick={() => {
                  if (variant.locked) return;
                  closeMenu();
                  void runJob(variant);
                }}
                className={cx(
                  "flex w-full flex-col gap-[3px] rounded-(--r-sm) px-2.5 py-[9px] text-start font-(family-name:--body-font) focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-(--purple)",
                  variant.locked
                    ? "cursor-default opacity-[0.62]"
                    : "cursor-pointer hover:bg-(--line-2)"
                )}
              >
                <span className="flex items-center gap-2">
                  {variant.locked ? LOCK_ICON : null}
                  <span
                    className={cx(
                      "text-[13px] font-semibold",
                      variant.locked ? "text-(--t-2)" : "text-(--t-1)"
                    )}
                  >
                    {copy.name}
                  </span>
                  {variant.locked ? (
                    <span className="ms-auto whitespace-nowrap rounded-[4px] bg-(--line-2) px-1.5 py-0.5 font-(family-name:--mono) text-[9.5px] uppercase tracking-[0.07em] text-(--t-3)">
                      {requirement}
                    </span>
                  ) : null}
                </span>
                <span className="text-[11.5px] leading-[1.4] text-(--t-3)">{copy.description}</span>
              </button>
            );
          })}
        </div>
      ) : null}

      {/* signal.css `.exp-panel`: the async job, persistent until dismissed. */}
      {job ? (
        <div
          role="status"
          className="absolute top-[calc(100%+8px)] z-60 w-[296px] rounded-(--r-md) border-0 bg-white p-3.5 shadow-[0_16px_40px_-16px_rgba(12,15,22,0.28)] end-0"
        >
          <div className="mb-2 flex items-center justify-between gap-2.5">
            <span className="font-(family-name:--disp) text-[13.5px] font-bold text-(--t-1)">
              {variantCopy(job.variant.key).name}
            </span>
            <button
              type="button"
              aria-label={t("signalExport.dismiss")}
              onClick={dismissJob}
              className="flex cursor-pointer rounded-md p-1 text-(--t-3) hover:bg-(--line-2) hover:text-(--t-1)"
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                aria-hidden="true"
                className="h-3.5 w-3.5"
                strokeWidth={2}
                strokeLinecap="round"
              >
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>

          <div className="mb-2.5 rounded-(--r-sm) border border-(--line-2) bg-(--paper) px-2.5 py-[9px] text-[12px] leading-[1.5] text-(--t-2)">
            <b className="mb-1 block font-(family-name:--mono) text-[11px] font-semibold uppercase tracking-[0.08em] text-(--t-3)">
              {t("signalExport.scopeHeading")}
            </b>
            <span>{variantCopy(job.variant.key).description}</span>
            <div className="mt-[5px] text-[11px] text-(--t-3)">{t("signalExport.scopeNote")}</div>
          </div>

          <div className="flex items-center gap-[9px] text-[12.5px] font-semibold text-(--t-1)">
            {job.state === "Queued" || job.state === "Preparing" ? (
              <span
                aria-hidden="true"
                className="h-3.5 w-3.5 flex-none animate-spin rounded-full border-2 border-(--line) border-t-(--purple) motion-reduce:animate-none"
              />
            ) : (
              <span
                aria-hidden="true"
                className={cx(
                  "h-2 w-2 flex-none rounded-full",
                  job.state === "Ready" ? "bg-(--good)" : "bg-(--bad)"
                )}
              />
            )}
            <span>{t(`signalExport.state.${job.state.toLowerCase()}`)}</span>
          </div>

          {job.state === "Ready" || job.state === "Failed" ? (
            <div className="mt-[7px] text-[12px] text-(--t-2)">
              {job.state === "Ready"
                ? t("signalExport.readyMessage")
                : job.expired
                  ? t("signalExport.expiredMessage")
                  : t("signalExport.failedMessage")}
            </div>
          ) : null}

          {job.state === "Ready" ? (
            <div className="mt-[11px] flex gap-2">
              <button
                type="button"
                onClick={() => void downloadReady()}
                className="inline-flex h-8 cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-3 font-(family-name:--body-font) text-[12.5px] font-semibold text-white hover:bg-black"
              >
                {t("signalExport.download")}
              </button>
              <Link
                href="/dashboard/reports"
                className="inline-flex h-8 cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-3 font-(family-name:--body-font) text-[12.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3]"
              >
                {t("signalExport.library")}
              </Link>
            </div>
          ) : null}

          {job.state === "Failed" ? (
            <div className="mt-[11px] flex gap-2">
              <button
                type="button"
                onClick={() => void runJob(job.variant)}
                className="inline-flex h-8 cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-3 font-(family-name:--body-font) text-[12.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3]"
              >
                {t("signalExport.tryAgain")}
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
