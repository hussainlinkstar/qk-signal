"use client";

// Built against Qiko-Signal-MVP-TBR/mockup/Signal Reports.html: the breadcrumb
// bar with a `Generate report` kind menu, the "Report library" pagehead, the
// dismissible withheld-sections alert, and one card holding the bulk action row
// and the approved datatable (Name, Kind, Period, Created, Size, Status, Link
// expiry, actions; five rows a page, rows selectable).
//
// Every cell is served by GET /api/v1/reports/complex. Nothing here is
// fabricated: the mockup's eight example rows are illustration and an empty
// library renders the approved empty state instead. Link expiry is the
// backend's answer about the stored artifact, so an expired link reads as
// expired here rather than being discovered on a dead download.
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { ChevronDown, FileText, Loader2 } from "lucide-react";

import { workspaceHeaders } from "@/components/app/WorkspaceSwitcher";
import { useAuth } from "@/components/auth/custom-auth";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import SignalAlert from "@/components/signal/SignalAlert";
import SignalCrumb from "@/components/signal/SignalCrumb";
import SignalDataTable, { type SignalDataTableColumn } from "@/components/signal/SignalDataTable";
import Modal from "@/components/ui/Modal";
import { cx } from "@/components/ui/utils";
import {
  deleteReports,
  downloadComplexReportPdfBlob,
  fetchReportLibrary,
  type ReportLibraryItem,
} from "@/services/reportService";

const REPORT_KINDS = [
  "standard",
  "aio",
  "seo",
  "executive",
  "project",
  "competitors",
  "financial",
] as const;

const PAGE_SIZE = 5;
const LIBRARY_PAGE_LIMIT = 100;

const btnCls =
  "inline-flex h-[38px] cursor-pointer items-center justify-center gap-2 rounded-(--r-md) border-0 bg-white px-[15px] font-(family-name:--body-font) text-[13px] font-semibold text-(--t-1) transition-colors duration-150 hover:bg-[#E8ECF3] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--brand) disabled:cursor-not-allowed disabled:opacity-45";
const btnSmCls =
  "inline-flex h-[30px] cursor-pointer items-center gap-1.5 rounded-(--r-sm) border-0 bg-white px-[11px] font-(family-name:--body-font) text-[12px] font-semibold text-(--t-1) hover:bg-[#E8ECF3] disabled:cursor-not-allowed disabled:opacity-45";
const btnSmGhostCls =
  "inline-flex h-[30px] cursor-pointer items-center gap-1.5 rounded-full border-0 bg-[#EEF1F6] px-[11px] font-(family-name:--body-font) text-[12px] font-semibold text-(--t-1) hover:bg-[#E8ECF3] disabled:cursor-not-allowed disabled:opacity-45";
const btnDangerCls =
  "inline-flex h-[38px] cursor-pointer items-center justify-center gap-2 rounded-(--r-md) border border-(--bad) bg-(--bad) px-[15px] font-(family-name:--body-font) text-[13px] font-semibold text-white transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-45";

const chipBase =
  "inline-flex items-center rounded-[6px] px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";

export default function ReportLibraryClient() {
  const { getToken, isSignedIn, isLoading: authLoading } = useAuth();
  const { t, i18n } = useTranslation();
  const { setHeader } = useWorkspacePageHeader();

  const [reports, setReports] = useState<ReportLibraryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [alertDismissed, setAlertDismissed] = useState(false);
  const [kindMenuOpen, setKindMenuOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const kindMenuRef = useRef<HTMLDivElement | null>(null);

  const authHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    return { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...workspaceHeaders() };
  }, [getToken]);

  const loadReports = useCallback(async () => {
    if (authLoading || !isSignedIn) {
      if (!authLoading) setLoading(false);
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      const headers = await authHeaders();
      const payload = await fetchReportLibrary(headers, { limit: LIBRARY_PAGE_LIMIT });
      setReports(payload.items);
      // Drop selections for rows that no longer exist, so a stale id can never
      // be sent to the delete route.
      const liveIds = new Set(payload.items.map((item) => item.report_id));
      setSelectedIds((current) => current.filter((id) => liveIds.has(id)));
    } catch (error) {
      setReports([]);
      setLoadError(error instanceof Error ? error.message : t("signalReportLibrary.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [authHeaders, authLoading, isSignedIn, t]);

  useEffect(() => {
    void loadReports();
  }, [loadReports]);

  useEffect(() => {
    if (!kindMenuOpen) return;
    const onDocumentPointerDown = (event: MouseEvent) => {
      if (!kindMenuRef.current?.contains(event.target as Node)) setKindMenuOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setKindMenuOpen(false);
    };
    document.addEventListener("mousedown", onDocumentPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onDocumentPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [kindMenuOpen]);

  const topBar = useMemo(
    () => ({
      crumb: (
        <SignalCrumb
          items={[
            { label: t("signalReportLibrary.crumbHome"), href: "/dashboard/overview" },
            { label: t("signalReportLibrary.crumbCurrent") },
          ]}
        />
      ),
      actions: (
        <div ref={kindMenuRef} className="relative">
          <button
            type="button"
            className={btnCls}
            aria-haspopup="menu"
            aria-expanded={kindMenuOpen}
            onClick={() => setKindMenuOpen((open) => !open)}
          >
            <FileText aria-hidden="true" className="h-4 w-4" />
            {t("signalReportLibrary.generate")}
            <ChevronDown aria-hidden="true" className="h-3.5 w-3.5" />
          </button>
          {kindMenuOpen ? (
            <div
              role="menu"
              aria-label={t("signalReportLibrary.generate")}
              className="absolute top-[calc(100%+6px)] z-dropdown min-w-[206px] overflow-hidden rounded-(--r-md) border-0 bg-white py-1 shadow-[0_18px_40px_-16px_var(--ink-sh)] ltr:right-0 rtl:left-0"
            >
              {REPORT_KINDS.map((kind) => (
                <Link
                  key={kind}
                  role="menuitem"
                  href={`/dashboard/reports/generate?kind=${kind}`}
                  onClick={() => setKindMenuOpen(false)}
                  className="block px-3.5 py-2 text-[13px] text-(--t-1) hover:bg-(--paper)"
                >
                  {t(`signalReportLibrary.kindMenu.${kind}`)}
                </Link>
              ))}
            </div>
          ) : null}
        </div>
      ),
    }),
    [kindMenuOpen, t]
  );

  useEffect(() => {
    setHeader(topBar);
    return () => setHeader(null);
  }, [setHeader, topBar]);

  // UTC, deliberately. The period is the interval the customer asked for, and
  // a request for "to 30 June" rendered in a local zone would read as 1 July
  // for anyone east of Greenwich.
  const dateFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(i18n.language || "en", {
        day: "numeric",
        month: "short",
        year: "numeric",
        timeZone: "UTC",
      }),
    [i18n.language]
  );
  const numberFormatter = useMemo(
    () => new Intl.NumberFormat(i18n.language || "en", { maximumFractionDigits: 1 }),
    [i18n.language]
  );

  const formatPeriod = useCallback(
    (item: ReportLibraryItem): string => {
      // Both ends absent is the recorded "all time" case. It is never filled in
      // from the span of the audits that happened to be selected, which would
      // be a claim the customer did not make.
      if (!item.period_start && !item.period_end) return t("signalReportLibrary.period.allTime");
      const start = item.period_start ? new Date(item.period_start) : null;
      const end = item.period_end ? new Date(item.period_end) : null;
      if (start && end) {
        if (dateFormatter.format(start) === dateFormatter.format(end))
          return dateFormatter.format(start);
        return t("signalReportLibrary.period.range", {
          from: dateFormatter.format(start),
          to: dateFormatter.format(end),
        });
      }
      if (start) return t("signalReportLibrary.period.from", { from: dateFormatter.format(start) });
      return t("signalReportLibrary.period.until", { to: dateFormatter.format(end as Date) });
    },
    [dateFormatter, t]
  );

  const formatCreated = useCallback(
    (value: string | null): string => {
      if (!value) return t("signalReportLibrary.dash");
      const created = new Date(value);
      if (Number.isNaN(created.getTime())) return t("signalReportLibrary.dash");
      const elapsedMinutes = Math.floor((Date.now() - created.getTime()) / 60000);
      if (elapsedMinutes < 1) return t("signalReportLibrary.created.justNow");
      if (elapsedMinutes < 60)
        return t("signalReportLibrary.created.minutes", { count: elapsedMinutes });
      const elapsedHours = Math.floor(elapsedMinutes / 60);
      if (elapsedHours < 24) return t("signalReportLibrary.created.hours", { count: elapsedHours });
      const elapsedDays = Math.floor(elapsedHours / 24);
      if (elapsedDays === 1) return t("signalReportLibrary.created.yesterday");
      if (elapsedDays < 30) return t("signalReportLibrary.created.days", { count: elapsedDays });
      return dateFormatter.format(created);
    },
    [dateFormatter, t]
  );

  const formatSize = useCallback(
    (bytes: number | null): string => {
      if (bytes === null || bytes <= 0) return t("signalReportLibrary.dash");
      if (bytes < 1024) return t("signalReportLibrary.size.bytes", { value: bytes });
      if (bytes < 1024 * 1024)
        return t("signalReportLibrary.size.kilobytes", {
          value: numberFormatter.format(Math.round(bytes / 1024)),
        });
      return t("signalReportLibrary.size.megabytes", {
        value: numberFormatter.format(Math.round((bytes / (1024 * 1024)) * 10) / 10),
      });
    },
    [numberFormatter, t]
  );

  const formatLinkExpiry = useCallback(
    (item: ReportLibraryItem): string => {
      if (item.link_expired) return t("signalReportLibrary.expiry.expired");
      if (item.expires_at === null || item.link_expiry_days_remaining === null)
        return t("signalReportLibrary.dash");
      if (item.link_expiry_days_remaining <= 0) return t("signalReportLibrary.expiry.today");
      if (item.link_expiry_days_remaining === 1) return t("signalReportLibrary.expiry.tomorrow");
      return t("signalReportLibrary.expiry.days", { count: item.link_expiry_days_remaining });
    },
    [t]
  );

  const handleDownload = useCallback(
    async (item: ReportLibraryItem) => {
      setActionError(null);
      setNotice(null);
      setDownloadingId(item.report_id);
      try {
        const headers = await authHeaders();
        const { blob, filename } = await downloadComplexReportPdfBlob(item.report_id, headers);
        const objectUrl = window.URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = objectUrl;
        link.download = filename || `${item.report_id}.pdf`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(() => window.URL.revokeObjectURL(objectUrl), 0);
      } catch (error) {
        setActionError(
          error instanceof Error ? error.message : t("signalReportLibrary.downloadFailed")
        );
        // A refused download means the row the browser is holding is stale
        // (expired or revoked since the list call), so re-read it.
        void loadReports();
      } finally {
        setDownloadingId(null);
      }
    },
    [authHeaders, loadReports, t]
  );

  const handleConfirmedDelete = useCallback(async () => {
    if (selectedIds.length === 0) return;
    setDeleting(true);
    setActionError(null);
    setNotice(null);
    try {
      const headers = await authHeaders();
      const result = await deleteReports(selectedIds, headers);
      setConfirmOpen(false);
      setSelectedIds([]);
      setNotice(t("signalReportLibrary.deleted", { count: result.deleted.length }));
      await loadReports();
    } catch (error) {
      setActionError(
        error instanceof Error ? error.message : t("signalReportLibrary.deleteFailed")
      );
    } finally {
      setDeleting(false);
    }
  }, [authHeaders, loadReports, selectedIds, t]);

  const statusChip = useCallback(
    (status: ReportLibraryItem["status"]) => {
      const toneClass =
        status === "succeeded"
          ? "bg-(--good-s) text-(--good)"
          : status === "running"
            ? "bg-(--warn-s) text-(--warn)"
            : status === "failed"
              ? "bg-(--bad-s) text-(--bad)"
              : status === "expired"
                ? "bg-(--line-2) text-(--t-3)"
                : "bg-(--purple-a10) text-(--purple)";
      return (
        <span className={cx(chipBase, toneClass)}>{t(`signalReportLibrary.status.${status}`)}</span>
      );
    },
    [t]
  );

  const columns: SignalDataTableColumn<ReportLibraryItem>[] = useMemo(
    () => [
      {
        key: "name",
        header: t("signalReportLibrary.columns.name"),
        sortable: true,
        sortValue: (row) => row.name,
        renderCell: (row) => <b className="font-bold text-(--t-1)">{row.name}</b>,
      },
      {
        key: "kind",
        header: t("signalReportLibrary.columns.kind"),
        sortable: true,
        sortValue: (row) => row.report_kind ?? "",
        renderCell: (row) =>
          row.report_kind ? (
            <span>
              {t(`signalReportLibrary.kind.${row.report_kind}`, {
                defaultValue: row.report_kind,
              })}
            </span>
          ) : (
            t("signalReportLibrary.dash")
          ),
      },
      {
        key: "period",
        header: t("signalReportLibrary.columns.period"),
        renderCell: (row) => formatPeriod(row),
      },
      {
        key: "created",
        header: t("signalReportLibrary.columns.created"),
        sortable: true,
        sortValue: (row) => row.created_at ?? "",
        renderCell: (row) => formatCreated(row.created_at),
      },
      {
        key: "size",
        header: t("signalReportLibrary.columns.size"),
        sortable: true,
        sortValue: (row) => row.size_bytes ?? 0,
        renderCell: (row) => formatSize(row.size_bytes),
      },
      {
        key: "status",
        header: t("signalReportLibrary.columns.status"),
        sortable: true,
        sortValue: (row) => row.status,
        renderCell: (row) => statusChip(row.status),
      },
      {
        key: "expiry",
        header: t("signalReportLibrary.columns.linkExpiry"),
        renderCell: (row) => formatLinkExpiry(row),
      },
      {
        key: "actions",
        header: "",
        align: "right",
        renderCell: (row) => (
          <button
            type="button"
            className={btnSmCls}
            // The approved rule: Download is live only on a succeeded report.
            // An expired link carries no download_url, so it is disabled here
            // too rather than offered and then refused with a 410.
            disabled={row.download_url === null || downloadingId === row.report_id}
            onClick={() => void handleDownload(row)}
          >
            {downloadingId === row.report_id ? (
              <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
            ) : null}
            {t("signalReportLibrary.download")}
          </button>
        ),
      },
    ],
    [
      downloadingId,
      formatCreated,
      formatLinkExpiry,
      formatPeriod,
      formatSize,
      handleDownload,
      statusChip,
      t,
    ]
  );

  const selectedCount = selectedIds.length;

  return (
    <div className="flex min-w-0 flex-col gap-[22px]">
      <DashboardPageIntro icon={FileText} title={t("signalReportLibrary.title")}>
        {t("signalReportLibrary.subtitle")}
      </DashboardPageIntro>

      {!alertDismissed ? (
        <SignalAlert
          role="note"
          title={t("signalReportLibrary.withheldTitle")}
          onDismiss={() => setAlertDismissed(true)}
          dismissLabel={t("signalReportLibrary.dismissAlert")}
        >
          {t("signalReportLibrary.withheldBody")}
        </SignalAlert>
      ) : null}

      {loadError ? (
        <SignalAlert tone="danger" role="alert" title={t("signalReportLibrary.loadFailed")}>
          {loadError}
        </SignalAlert>
      ) : null}

      {actionError ? (
        <SignalAlert tone="danger" role="alert" title={t("signalReportLibrary.actionFailed")}>
          {actionError}
        </SignalAlert>
      ) : null}

      {notice ? (
        <SignalAlert tone="success" title={t("signalReportLibrary.actionDone")}>
          {notice}
        </SignalAlert>
      ) : null}

      <div className="rounded-(--r-lg) border-0 bg-white px-[18px] py-4">
        <div className="mb-2.5 flex flex-wrap items-center gap-2">
          <button
            type="button"
            className={btnSmCls}
            disabled={selectedCount === 0}
            onClick={() => setConfirmOpen(true)}
          >
            {t("signalReportLibrary.deleteSelected")}
          </button>
          {selectedCount > 0 ? (
            <button type="button" className={btnSmGhostCls} onClick={() => setSelectedIds([])}>
              {t("signalReportLibrary.clearSelection")}
            </button>
          ) : null}
        </div>

        {loading ? (
          <div
            role="status"
            className="flex items-center gap-2.5 px-1 py-[34px] text-[13px] text-(--t-3)"
          >
            <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
            {t("signalReportLibrary.loading")}
          </div>
        ) : (
          <SignalDataTable
            columns={columns}
            rows={reports}
            rowKey={(row) => row.report_id}
            pageSize={PAGE_SIZE}
            searchPlaceholder={t("signalReportLibrary.filterRows")}
            searchText={(row) => `${row.name} ${row.report_kind ?? ""} ${row.status}`}
            metaLabel={
              selectedCount > 0
                ? t("signalReportLibrary.metaWithSelection", {
                    rows: reports.length,
                    selected: selectedCount,
                  })
                : t("signalReportLibrary.meta", { count: reports.length })
            }
            emptyLabel={t("signalReportLibrary.empty")}
            selectable
            selectedKeys={selectedIds}
            onSelectionChange={(keys) => setSelectedIds(keys.map((key) => String(key)))}
            selectAllLabel={t("signalReportLibrary.selectAll")}
            selectRowLabel={t("signalReportLibrary.selectRow")}
          />
        )}
      </div>

      <div className="text-[12.5px] leading-[1.5] text-(--t-3)">
        {t("signalReportLibrary.kindsNote")}
      </div>

      {/* Deletion is irreversible and removes the stored PDF, so it never fires
          on a single click. */}
      <Modal
        open={confirmOpen}
        onClose={() => (deleting ? undefined : setConfirmOpen(false))}
        ariaLabelledby="report-library-delete-title"
        panelClassName="max-w-[420px] border-0 bg-white p-[22px]"
      >
        <div className="flex flex-col gap-3">
          <h2
            id="report-library-delete-title"
            className="m-0 font-(family-name:--disp) text-[17px] font-bold text-(--t-1)"
          >
            {t("signalReportLibrary.confirmTitle")}
          </h2>
          <p className="m-0 text-[13px] leading-[1.5] text-(--t-2)">
            {t("signalReportLibrary.confirmBody", { count: selectedCount })}
          </p>
          <div className="mt-1 flex justify-end gap-2">
            <button
              type="button"
              className={btnCls}
              disabled={deleting}
              onClick={() => setConfirmOpen(false)}
            >
              {t("signalReportLibrary.confirmCancel")}
            </button>
            <button
              type="button"
              className={btnDangerCls}
              disabled={deleting || selectedCount === 0}
              onClick={() => void handleConfirmedDelete()}
            >
              {deleting ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> : null}
              {t("signalReportLibrary.confirmDelete")}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
