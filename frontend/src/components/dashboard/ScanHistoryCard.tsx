"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";

import { useAuth } from "@/components/auth/custom-auth";
import { NativeSelect } from "@/components/ui/native-select";
import { cx } from "@/components/ui/utils";
import { fetchProjectAudits, type ProjectAuditHistoryEntry } from "@/services/workspaceService";
import { fetchAuditById } from "@/services/auditService";
import { DEFAULT_SECTIONS, generateAuditPdfReport } from "@/lib/generateAuditPdfReport";
import { normalizeAuditReport } from "@/lib/reportAdapters";
import { extractAuditStatus, type AuditDisplayStatus } from "@/lib/auditListUtils";
import { getTierShort } from "@/constants/tiers";
import type { AuditHistoryItem } from "@/types/auditWorkspace";

export const SCAN_HISTORY_ANCHOR = "scan-history";

type HistoryFilter = "all" | "completed" | "failed";

/* The filter's "Completed" bucket means the run finished and produced results;
   a degraded, archived or purged scan still did that. Failed is the only other
   terminal group the approved filter offers. */
const matchesFilter = (status: AuditDisplayStatus, filter: HistoryFilter): boolean => {
  if (filter === "all") return true;
  if (filter === "failed") return status === "failed";
  return status !== "failed" && status !== "unknown";
};

/** A stored report payload exists to export for these states only. */
const canDownloadPdf = (status: AuditDisplayStatus): boolean =>
  status === "completed" || status === "degraded" || status === "archived";

const formatScanDate = (raw: string | null | undefined): string => {
  if (!raw) return "N/A";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return "N/A";
  // Approved format is day-first long date: "6 October 2026".
  return date.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
};

const formatScore = (value: number | null | undefined): string =>
  typeof value === "number" && Number.isFinite(value) ? String(Math.round(value)) : "N/A";

const STATUS_CHIP_CLASS: Record<AuditDisplayStatus, string> = {
  completed: "bg-(--good-s) text-[#18683B]",
  failed: "bg-(--bad-s) text-[#AD3036]",
  degraded: "bg-(--warn-s) text-(--warn)",
  archived: "bg-(--surface-subtle) text-(--t-2)",
  purged: "bg-(--surface-subtle) text-(--t-2)",
  unknown: "bg-(--surface-subtle) text-(--t-2)",
};

const STATUS_LABEL_KEY: Record<AuditDisplayStatus, string> = {
  completed: "signalScanHistory.statusCompleted",
  failed: "signalScanHistory.statusFailed",
  degraded: "signalScanHistory.statusDegraded",
  archived: "signalScanHistory.statusArchived",
  purged: "signalScanHistory.statusPurged",
  unknown: "signalScanHistory.statusUnknown",
};

type ScanHistoryCardProps = {
  projectId: string | number;
  projectName?: string | null;
  className?: string;
};

/**
 * Approved `details.card.scan-history` on the project dashboard (SIGV2-1187):
 * the scan log moved off the Start a scan page and lives here instead, so the
 * project dashboard carries the project-wide timeline the design assigns it.
 * Rows are fetched per project id, never shared across projects, and each
 * completed row exports its PDF on demand: the list payload is kept light
 * (no full reports) and the report body is pulled lazily on click.
 * `#scan-history` deep links auto-expand the card, matching the mockup.
 */
export function ScanHistoryCard({ projectId, projectName, className }: ScanHistoryCardProps) {
  const { t } = useTranslation();
  const { getToken, isSignedIn, isLoading: authLoading } = useAuth();

  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState<HistoryFilter>("all");
  const [audits, setAudits] = useState<ProjectAuditHistoryEntry[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [pdfBusyId, setPdfBusyId] = useState<number | null>(null);
  const [pdfErrorId, setPdfErrorId] = useState<number | null>(null);

  const getAuthHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to load scan history.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  // The mockup opens the card for `#scan-history` links, including the one the
  // finished run view points at ("View scan history and PDFs").
  useEffect(() => {
    if (typeof window === "undefined") return;
    const openFromHash = () => {
      if (window.location.hash === `#${SCAN_HISTORY_ANCHOR}`) setOpen(true);
    };
    openFromHash();
    window.addEventListener("hashchange", openFromHash);
    return () => window.removeEventListener("hashchange", openFromHash);
  }, []);

  useEffect(() => {
    if (!projectId || authLoading || !isSignedIn) return;
    let cancelled = false;
    void (async () => {
      try {
        const headers = await getAuthHeaders();
        const rows = await fetchProjectAudits(projectId, headers, { limit: 100 });
        if (cancelled) return;
        const sorted = [...rows].sort(
          (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
        );
        setAudits(sorted);
        setLoadFailed(false);
      } catch {
        if (!cancelled) setLoadFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, authLoading, isSignedIn, getAuthHeaders]);

  const visible = useMemo(
    () => (audits ?? []).filter((audit) => matchesFilter(extractAuditStatus(audit), filter)),
    [audits, filter]
  );

  const handleDownload = useCallback(
    async (audit: ProjectAuditHistoryEntry) => {
      setPdfBusyId(audit.id);
      setPdfErrorId(null);
      try {
        const headers = await getAuthHeaders();
        const record = await fetchAuditById(audit.id, headers);
        const rawReport = record.full_report;
        const reportData =
          typeof rawReport === "string"
            ? (JSON.parse(rawReport) as Record<string, unknown>)
            : (rawReport as Record<string, unknown> | null | undefined);
        if (!reportData || typeof reportData !== "object") {
          throw new Error("No saved report is available for this audit.");
        }
        const canonical = normalizeAuditReport(reportData);
        const meta: AuditHistoryItem = {
          id: audit.id,
          url: audit.url,
          targetName: audit.target_name ?? String(canonical.site?.url ?? audit.url ?? ""),
          targetUrl: audit.target_url ?? audit.url,
          geoScore: audit.geo_score,
          seoScore: audit.seo_score,
          aeoScore: audit.aeo_score,
          status: audit.status,
          auditType: audit.audit_type,
          createdAt: audit.created_at,
          projectId: audit.project_id,
        };
        await generateAuditPdfReport(canonical, meta, DEFAULT_SECTIONS);
      } catch (err) {
        console.error("Scan history PDF export failed:", err);
        setPdfErrorId(audit.id);
      } finally {
        setPdfBusyId((current) => (current === audit.id ? null : current));
      }
    },
    [getAuthHeaders]
  );

  const captionText = projectName?.trim()
    ? t("signalScanHistory.captionNamed", { project: projectName.trim() })
    : t("signalScanHistory.caption");

  const retryHref = `/dashboard/audit?projectId=${encodeURIComponent(String(projectId))}`;

  return (
    <details
      id={SCAN_HISTORY_ANCHOR}
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      className={cx(
        "scroll-mt-[88px] overflow-hidden rounded-(--r) border border-(--line) bg-(--panel)",
        className
      )}
    >
      <summary className="flex cursor-pointer list-none items-center gap-4 px-[22px] py-5 [&::-webkit-details-marker]:hidden">
        <div className="min-w-0 flex-1">
          <h2 className="m-0 mb-[5px] font-(family-name:--disp) text-[17px] font-bold leading-[normal]">
            {t("signalScanHistory.heading")}
          </h2>
          <p className="m-0 text-[12px] leading-[1.65] text-(--t-2)">
            {t("signalScanHistory.intro")}
          </p>
        </div>
        <span className="whitespace-nowrap font-mono text-[11px] text-(--t-2)">
          {audits === null
            ? t("signalScanHistory.countLoading")
            : t("signalScanHistory.count", { count: audits.length })}
        </span>
        <span
          aria-hidden="true"
          className={cx(
            "text-[22px] leading-none text-(--t-2) transition-transform duration-200",
            open && "rotate-45"
          )}
        >
          +
        </span>
      </summary>

      <div className="border-t border-(--line) px-[22px] py-4">
        <div className="mb-3.5 flex flex-wrap items-center gap-3 text-[12px] text-(--t-1)">
          <label htmlFor="scan-history-filter">{t("signalScanHistory.filterShow")}</label>
          <NativeSelect
            id="scan-history-filter"
            value={filter}
            onChange={(event) => setFilter(event.target.value as HistoryFilter)}
            className="h-[34px] w-[160px] text-[12px]"
          >
            <option value="all">{t("signalScanHistory.filterAll")}</option>
            <option value="completed">{t("signalScanHistory.filterCompleted")}</option>
            <option value="failed">{t("signalScanHistory.filterFailed")}</option>
          </NativeSelect>
          <span className="ms-auto text-[11px] text-(--t-2) max-md:ms-0">
            {t("signalScanHistory.newestFirst")}
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-start">
            <caption className="pb-3 text-start text-[12px] text-(--t-2)">{captionText}</caption>
            <thead>
              <tr>
                <th className="px-3 py-2.5 text-start font-mono text-[10px] font-normal uppercase text-(--t-2)">
                  {t("signalScanHistory.colScan")}
                </th>
                <th className="px-3 py-2.5 text-start font-mono text-[10px] font-normal uppercase text-(--t-2)">
                  {t("signalScanHistory.colAio")}
                </th>
                <th className="px-3 py-2.5 text-start font-mono text-[10px] font-normal uppercase text-(--t-2)">
                  {t("signalScanHistory.colSeo")}
                </th>
                <th className="px-3 py-2.5 text-start font-mono text-[10px] font-normal uppercase text-(--t-2)">
                  {t("signalScanHistory.colStatus")}
                </th>
                <th className="px-3 py-2.5 text-start font-mono text-[10px] font-normal uppercase text-(--t-2)">
                  {t("signalScanHistory.colReport")}
                </th>
              </tr>
            </thead>
            <tbody>
              {audits === null && !loadFailed ? (
                <tr>
                  <td
                    colSpan={5}
                    className="border-t border-(--line) px-3 py-6 text-[13px] text-(--t-2)"
                  >
                    {t("signalScanHistory.loading")}
                  </td>
                </tr>
              ) : loadFailed ? (
                <tr>
                  <td
                    colSpan={5}
                    className="border-t border-(--line) px-3 py-6 text-[13px] text-(--t-2)"
                  >
                    {t("signalScanHistory.loadFailed")}
                  </td>
                </tr>
              ) : visible.length === 0 ? (
                <tr>
                  <td
                    colSpan={5}
                    className="border-t border-(--line) px-3 py-6 text-[13px] text-(--t-2)"
                  >
                    {filter === "all"
                      ? t("signalScanHistory.empty")
                      : t("signalScanHistory.emptyFiltered")}
                  </td>
                </tr>
              ) : (
                visible.map((audit, index) => {
                  const status = extractAuditStatus(audit);
                  const busy = pdfBusyId === audit.id;
                  const failed = pdfErrorId === audit.id;
                  return (
                    <tr key={audit.id} data-scan-status={status}>
                      <td className="whitespace-nowrap border-t border-(--line) px-3 py-4 align-top text-[13px]">
                        <strong className="font-semibold">
                          {formatScanDate(audit.created_at)}
                        </strong>
                        <small className="mt-1.5 block text-[11px] text-(--t-2)">
                          {index === 0 && filter === "all"
                            ? `${t("signalScanHistory.latestScan")} · ${getTierShort(audit.audit_type)}`
                            : getTierShort(audit.audit_type)}
                        </small>
                      </td>
                      {/* A failed run produced no measurement - printing the
                          stored 0 would claim a real score, so it reads N/A
                          like the approved design. */}
                      <td className="whitespace-nowrap border-t border-(--line) px-3 py-4 align-top text-[13px]">
                        {status === "failed" ? "N/A" : formatScore(audit.geo_score)}
                      </td>
                      <td className="whitespace-nowrap border-t border-(--line) px-3 py-4 align-top text-[13px]">
                        {status === "failed" ? "N/A" : formatScore(audit.seo_score)}
                      </td>
                      <td className="whitespace-nowrap border-t border-(--line) px-3 py-4 align-top">
                        <span
                          className={cx(
                            "inline-block rounded-md px-2 py-[5px] text-[11px]",
                            STATUS_CHIP_CLASS[status]
                          )}
                        >
                          {t(STATUS_LABEL_KEY[status])}
                        </span>
                      </td>
                      <td className="whitespace-nowrap border-t border-(--line) px-3 py-4 align-top">
                        {status === "failed" ? (
                          <>
                            <Link
                              href={retryHref}
                              className="inline-flex h-7 items-center rounded-full border border-(--line) px-3 text-[12px] font-semibold text-(--t-1) hover:bg-(--surface-subtle)"
                            >
                              {t("signalScanHistory.retryScan")}
                            </Link>
                            <small className="mt-1.5 block text-[11px] text-(--t-2)">
                              {t("signalScanHistory.noReport")}
                            </small>
                          </>
                        ) : canDownloadPdf(status) ? (
                          <>
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void handleDownload(audit)}
                              className={cx(
                                "inline-flex h-7 items-center gap-1.5 rounded-full border border-(--line) px-3 text-[12px] font-semibold text-(--t-1) hover:bg-(--surface-subtle)",
                                busy && "cursor-wait opacity-80"
                              )}
                            >
                              {busy ? (
                                <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
                              ) : null}
                              {busy
                                ? t("signalScanHistory.preparingPdf")
                                : t("signalScanHistory.downloadPdf")}
                            </button>
                            {busy ? (
                              <small className="mt-1.5 block text-[11px] text-(--t-2)">
                                {t("signalScanHistory.preparingNote")}
                              </small>
                            ) : failed ? (
                              <small className="mt-1.5 block text-[11px] text-(--bad)">
                                {t("signalScanHistory.pdfFailed")}
                              </small>
                            ) : null}
                          </>
                        ) : (
                          <small className="block text-[11px] text-(--t-2)">
                            {status === "purged"
                              ? t("signalScanHistory.reportDeleted")
                              : t("signalScanHistory.noReport")}
                          </small>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        <p className="m-0 mt-4 text-[12px] leading-[1.65] text-(--t-2)" role="status">
          {t("signalScanHistory.summary", { count: visible.length })}
        </p>
      </div>
    </details>
  );
}

export default ScanHistoryCard;
