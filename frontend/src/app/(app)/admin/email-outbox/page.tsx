"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  Search,
  ChevronLeft,
  ChevronRight,
  RefreshCcw,
  Download,
  X,
  Mail,
  AlertTriangle,
  Clock,
  CheckCircle2,
  XCircle,
  RotateCcw,
  Eye,
} from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import { ClientSafeDate } from "@/lib/dateFormat";
import { useDebounce } from "@/hooks/useDebounce";
import Button from "@/components/ui/Button";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import SignalDataTable, { type SignalDataTableColumn } from "@/components/signal/SignalDataTable";
import Modal from "@/components/ui/Modal";
import ToggleSwitch from "@/components/ui/ToggleSwitch";
import { NativeSelect } from "@/components/ui/native-select";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { AdminInlineError } from "@/components/admin/AdminInlineError";
import { AdminTableSkeleton } from "@/components/admin/AdminTableSkeleton";

/* -------------------------------------------------------------------------- */
/*  Types                                                                      */
/* -------------------------------------------------------------------------- */

type EmailEntry = {
  id: number;
  user_id: number | null;
  to_email: string;
  subject: string;
  category: string | null;
  template_key: string | null;
  correlation_id: string | null;
  status: string;
  provider: string | null;
  attempts: number;
  last_error: string | null;
  created_at: string;
  sent_at: string | null;
};

type EmailPage = {
  items: EmailEntry[];
  total: number;
  page: number;
  page_size: number;
};

type EmailDetail = EmailEntry & {
  user_email: string | null;
  html_body: string | null;
  text_body: string | null;
  updated_at: string | null;
};

type EmailStats = {
  total: number;
  pending: number;
  sent: number;
  failed: number;
  retry: number;
  delivery_rate: number;
  avg_attempts: number;
  top_errors: { label: string; count: number }[];
  by_template: { template_key: string; sent: number; failed: number; pending: number }[];
};

/* -------------------------------------------------------------------------- */
/*  Constants                                                                  */
/* -------------------------------------------------------------------------- */

const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const MONO_META = MICRO_LABEL.replace("uppercase ", "");
const WSTAT = "rounded-[22px] border-0 bg-white px-4 py-3";
const WSTAT_VALUE =
  "font-(family-name:--disp) text-[20px] font-bold leading-none tracking-[-0.02em] text-(--t-1)";
const WSEC = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";
const WINPUT_SM =
  "field-focus-ring h-8 rounded-(--r-md) border-0 bg-[#EEF1F6] px-[10px] text-[12.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6]";
const CHIP =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";
const PAGER_BTN =
  "inline-flex h-8 min-w-8 items-center justify-center rounded-(--r-sm) px-2 text-(--t-2) hover:bg-(--line-2) hover:text-(--t-1) disabled:opacity-40";

const STATUS_CONFIG: Record<string, { label: string; chip: string; icon: React.ReactNode }> = {
  sent: {
    label: "Sent",
    chip: `${CHIP} text-(--good) bg-(--good-s)`,
    icon: <CheckCircle2 size={10} />,
  },
  pending: {
    label: "Pending",
    chip: `${CHIP} text-(--warn) bg-(--warn-s)`,
    icon: <Clock size={10} />,
  },
  retry: {
    label: "Retry",
    chip: `${CHIP} text-(--warn) bg-(--warn-s)`,
    icon: <RotateCcw size={10} />,
  },
  failed: {
    label: "Failed",
    chip: `${CHIP} text-(--bad) bg-(--bad-s)`,
    icon: <XCircle size={10} />,
  },
};

const CATEGORY_CHIP: Record<string, string> = {
  account_notification: `${CHIP} text-(--purple) bg-(--purple-s)`,
  billing: `${CHIP} text-(--purple) bg-(--purple-s)`,
  audit_notification: `${CHIP} text-(--purple) bg-(--purple-s)`,
  system_alert: `${CHIP} text-(--warn) bg-(--warn-s)`,
  alert_notification: `${CHIP} text-(--bad) bg-(--bad-s)`,
  report_delivery: `${CHIP} text-(--good) bg-(--good-s)`,
};
const CHIP_NEUTRAL = `${CHIP} text-(--t-2) bg-(--line-2)`;

const STATUSES = ["pending", "retry", "sent", "failed"];

const CATEGORIES = [
  "account_notification",
  "billing",
  "audit_notification",
  "system_alert",
  "alert_notification",
  "report_delivery",
];

/* -------------------------------------------------------------------------- */
/*  Summary Card                                                               */
/* -------------------------------------------------------------------------- */

function StatCard({ title, value, subtitle }: { title: string; value: string; subtitle?: string }) {
  return (
    <div className={WSTAT}>
      <span className={WSTAT_VALUE}>{value}</span>
      <span className={MICRO_LABEL}>{title}</span>
      {subtitle && <span className="text-[11px] text-(--purple)">{subtitle}</span>}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Detail Modal                                                               */
/* -------------------------------------------------------------------------- */

function DetailModal({
  detail,
  isLoading,
  onClose,
  onResend,
  isResending,
}: {
  detail: EmailDetail | null;
  isLoading: boolean;
  onClose: () => void;
  onResend: (id: number) => void;
  isResending: boolean;
}) {
  const [showHtml, setShowHtml] = useState(true);
  const titleId = React.useId();

  if (!detail && !isLoading) return null;

  const statusCfg = detail
    ? (STATUS_CONFIG[detail.status] ?? STATUS_CONFIG.pending)
    : STATUS_CONFIG.pending;

  return (
    <Modal
      open
      onClose={onClose}
      title="Email detail"
      ariaLabelledby={titleId}
      panelClassName="w-[720px]"
    >
      <div className="mb-5 flex items-start justify-between">
        <div>
          <h2
            id={titleId}
            className="m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)"
          >
            Email detail
          </h2>
          <p className={`${MONO_META} mt-1`}>
            {detail ? `#${detail.id} · ${detail.to_email}` : "Loading..."}
          </p>
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          className="flex h-8 w-8 items-center justify-center rounded-(--r-sm) border-0 bg-white text-(--t-2) transition-colors hover:text-(--t-1)"
        >
          <X size={16} />
        </button>
      </div>

      <div className="max-h-[70vh] space-y-4 overflow-y-auto">
        {isLoading ? (
          <p className={`${MONO_META} py-12 text-center`}>Loading email details...</p>
        ) : detail ? (
          <>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className={`${MICRO_LABEL} mb-1`}>Recipient</p>
                <p className="text-sm font-semibold text-(--t-1)">{detail.to_email}</p>
              </div>
              <div>
                <p className={`${MICRO_LABEL} mb-1`}>Status</p>
                <span className={statusCfg.chip}>
                  {statusCfg.icon} {statusCfg.label}
                </span>
              </div>
              <div className="col-span-2">
                <p className={`${MICRO_LABEL} mb-1`}>Subject</p>
                <p className="text-sm font-semibold text-(--t-1)">{detail.subject}</p>
              </div>
              <div>
                <p className={`${MICRO_LABEL} mb-1`}>Category</p>
                <p className="text-sm font-semibold text-(--t-1)">{detail.category ?? "-"}</p>
              </div>
              <div>
                <p className={`${MICRO_LABEL} mb-1`}>Provider</p>
                <p className="text-sm font-semibold text-(--t-1)">{detail.provider ?? "-"}</p>
              </div>
              <div>
                <p className={`${MICRO_LABEL} mb-1`}>Attempts</p>
                <p className="text-sm font-semibold text-(--t-1)">{detail.attempts}</p>
              </div>
              <div>
                <p className={`${MICRO_LABEL} mb-1`}>User</p>
                <p className="text-sm font-semibold text-(--t-1)">{detail.user_email ?? "-"}</p>
              </div>
              <div>
                <p className={`${MICRO_LABEL} mb-1`}>Created</p>
                <p className="text-sm font-semibold text-(--t-1)">
                  <ClientSafeDate date={detail.created_at} format="datetime" />
                </p>
              </div>
              <div>
                <p className={`${MICRO_LABEL} mb-1`}>Sent at</p>
                <p className="text-sm font-semibold text-(--t-1)">
                  {detail.sent_at ? (
                    <ClientSafeDate date={detail.sent_at} format="datetime" />
                  ) : (
                    "-"
                  )}
                </p>
              </div>
            </div>

            {detail.last_error && (
              <Alert variant="destructive">
                <AlertTriangle />
                <AlertDescription>
                  <p className={`${MICRO_LABEL} mb-1 text-(--bad)`}>Last error</p>
                  <p className="whitespace-pre-wrap font-(family-name:--mono) text-xs">
                    {detail.last_error}
                  </p>
                </AlertDescription>
              </Alert>
            )}

            {/* Email body preview */}
            {(detail.html_body || detail.text_body) && (
              <div>
                <div className="mb-2 flex items-center gap-2">
                  <p className={MICRO_LABEL}>Email body</p>
                  {detail.html_body && detail.text_body && (
                    <div className="ml-auto flex items-center gap-1">
                      <button
                        onClick={() => setShowHtml(true)}
                        className={`rounded-md px-2 py-1 font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] transition-colors ${showHtml ? "bg-(--purple-s) text-(--purple)" : "text-(--t-3) hover:text-(--t-2)"}`}
                      >
                        HTML
                      </button>
                      <button
                        onClick={() => setShowHtml(false)}
                        className={`rounded-md px-2 py-1 font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] transition-colors ${!showHtml ? "bg-(--purple-s) text-(--purple)" : "text-(--t-3) hover:text-(--t-2)"}`}
                      >
                        Text
                      </button>
                    </div>
                  )}
                </div>
                <div className="max-h-[300px] overflow-hidden overflow-y-auto rounded-(--r-md) border-0 bg-[#EEF1F6]">
                  {showHtml && detail.html_body ? (
                    <iframe
                      srcDoc={detail.html_body}
                      sandbox="allow-same-origin"
                      className="h-[300px] w-full border-0"
                      title="Email preview"
                    />
                  ) : (
                    <pre className="whitespace-pre-wrap p-4 font-(family-name:--mono) text-[12px] leading-[1.7] text-(--t-1)">
                      {detail.text_body ?? "No text body available."}
                    </pre>
                  )}
                </div>
              </div>
            )}
          </>
        ) : null}
      </div>

      <div className="mt-5 flex justify-between border-t border-(--line-2) pt-4">
        {detail && detail.status !== "sent" && (
          <Button
            variant="primary"
            size="sm"
            onClick={() => onResend(detail.id)}
            disabled={isResending}
          >
            <RotateCcw size={14} className={isResending ? "animate-spin" : ""} />
            {isResending ? "Resending..." : "Resend email"}
          </Button>
        )}
        <div className="ml-auto">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </Modal>
  );
}

/* -------------------------------------------------------------------------- */
/*  Main Page                                                                  */
/* -------------------------------------------------------------------------- */

export default function EmailOutboxPage() {
  const { getToken, isSignedIn } = useAuth();
  const { isAdmin, isLoading: isGuardLoading } = useAdminAccess();

  /* Data */
  const [emails, setEmails] = useState<EmailEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<EmailStats | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  /* Detail modal */
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<EmailDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [isResending, setIsResending] = useState(false);

  /* Pagination */
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  /* Filters */
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [hasErrorFilter, setHasErrorFilter] = useState(false);

  /* Auto-refresh */
  const [autoRefresh, setAutoRefresh] = useState(false);

  const debouncedSearch = useDebounce(searchQuery, 400);
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const controlsDisabled = isLoading || !isAdmin;

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) throw new Error("You must be signed in to access admin data.");
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  /* Fetch list */
  const loadEmails = useCallback(async () => {
    if (!isSignedIn) return;
    setIsLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (debouncedSearch.trim()) params.set("search", debouncedSearch.trim());
      if (statusFilter) params.set("status", statusFilter);
      if (categoryFilter) params.set("category", categoryFilter);
      if (dateFrom) params.set("date_from", dateFrom);
      if (dateTo) params.set("date_to", dateTo);
      if (hasErrorFilter) params.set("has_error", "true");

      const response = await fetch(`/api/admin/email-outbox?${params.toString()}`, { headers });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load email outbox.");
      }
      const payload = (await response.json()) as EmailPage;
      setEmails(payload.items);
      setTotal(payload.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load email outbox.");
    } finally {
      setIsLoading(false);
    }
  }, [
    getAuthHeaders,
    isSignedIn,
    page,
    pageSize,
    debouncedSearch,
    statusFilter,
    categoryFilter,
    dateFrom,
    dateTo,
    hasErrorFilter,
  ]);

  /* Fetch stats */
  const loadStats = useCallback(async () => {
    if (!isSignedIn) return;
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/admin/email-outbox/stats", { headers });
      if (response.ok) {
        const payload = (await response.json()) as EmailStats;
        setStats(payload);
      }
    } catch {
      /* non-critical */
    }
  }, [getAuthHeaders, isSignedIn]);

  /* Fetch detail */
  const loadDetail = useCallback(
    async (id: number) => {
      setSelectedId(id);
      setDetailLoading(true);
      setDetail(null);
      try {
        const headers = await getAuthHeaders();
        const response = await fetch(`/api/admin/email-outbox/${id}`, { headers });
        if (!response.ok) {
          const payload = await response.json().catch(() => null);
          throw new Error(payload?.detail ?? "Unable to load email detail.");
        }
        const payload = (await response.json()) as EmailDetail;
        setDetail(payload);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to load email detail.");
        setSelectedId(null);
      } finally {
        setDetailLoading(false);
      }
    },
    [getAuthHeaders]
  );

  /* Resend */
  const handleResend = useCallback(
    async (id: number) => {
      setIsResending(true);
      try {
        const headers = await getAuthHeaders();
        const response = await fetch(`/api/admin/email-outbox/${id}/resend`, {
          method: "POST",
          headers,
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => null);
          throw new Error(payload?.detail ?? "Unable to resend email.");
        }
        // Refresh data
        loadEmails();
        loadStats();
        if (selectedId === id) {
          loadDetail(id);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to resend email.");
      } finally {
        setIsResending(false);
      }
    },
    [getAuthHeaders, loadEmails, loadStats, selectedId, loadDetail]
  );

  useEffect(() => {
    loadEmails();
  }, [loadEmails]);
  useEffect(() => {
    loadStats();
  }, [loadStats]);
  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, statusFilter, categoryFilter, dateFrom, dateTo, hasErrorFilter, pageSize]);

  /* Auto-refresh */
  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(() => {
      loadEmails();
      loadStats();
    }, 30000);
    return () => clearInterval(interval);
  }, [autoRefresh, loadEmails, loadStats]);

  /* CSV Export */
  const handleExport = useCallback(async () => {
    if (!isSignedIn) return;
    try {
      const headers = await getAuthHeaders();
      const params = new URLSearchParams({ page: "1", page_size: "10000" });
      if (debouncedSearch.trim()) params.set("search", debouncedSearch.trim());
      if (statusFilter) params.set("status", statusFilter);
      if (categoryFilter) params.set("category", categoryFilter);
      if (dateFrom) params.set("date_from", dateFrom);
      if (dateTo) params.set("date_to", dateTo);
      if (hasErrorFilter) params.set("has_error", "true");

      const response = await fetch(`/api/admin/email-outbox?${params.toString()}`, { headers });
      if (!response.ok) return;
      const payload = (await response.json()) as EmailPage;

      const csvRows = [
        ["ID", "Created", "Recipient", "Subject", "Category", "Status", "Attempts", "Error"].join(
          ","
        ),
        ...payload.items.map((item) =>
          [
            item.id,
            item.created_at,
            item.to_email,
            `"${item.subject.replace(/"/g, '""')}"`,
            item.category ?? "",
            item.status,
            item.attempts,
            item.last_error ? `"${item.last_error.replace(/"/g, '""').slice(0, 200)}"` : "",
          ].join(",")
        ),
      ].join("\n");

      const blob = new Blob([csvRows], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `email-outbox-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      /* best-effort */
    }
  }, [
    getAuthHeaders,
    isSignedIn,
    debouncedSearch,
    statusFilter,
    categoryFilter,
    dateFrom,
    dateTo,
    hasErrorFilter,
  ]);

  const columns: SignalDataTableColumn<EmailEntry>[] = [
    {
      key: "id",
      header: "ID",
      renderCell: (entry) => (
        <span className="font-(family-name:--mono) text-xs text-(--t-3)">#{entry.id}</span>
      ),
    },
    {
      key: "timestamp",
      header: "Timestamp",
      renderCell: (entry) => (
        <span className="text-(--t-2)">
          <ClientSafeDate date={entry.created_at} format="datetime" />
        </span>
      ),
    },
    {
      key: "recipient",
      header: "Recipient",
      renderCell: (entry) => (
        <span className="block max-w-[200px] truncate font-semibold text-(--t-1)">
          {entry.to_email}
        </span>
      ),
    },
    {
      key: "subject",
      header: "Subject",
      renderCell: (entry) => (
        <span className="block max-w-[250px] truncate text-(--t-2)" title={entry.subject}>
          {entry.subject}
        </span>
      ),
    },
    {
      key: "category",
      header: "Category",
      renderCell: (entry) =>
        entry.category ? (
          <span className={CATEGORY_CHIP[entry.category] ?? CHIP_NEUTRAL}>
            {entry.category.replace(/_/g, " ")}
          </span>
        ) : (
          <span className="text-xs text-(--t-3)">-</span>
        ),
    },
    {
      key: "status",
      header: "Status",
      renderCell: (entry) => {
        const statusCfg = STATUS_CONFIG[entry.status] ?? STATUS_CONFIG.pending;
        return (
          <span className={statusCfg.chip}>
            {statusCfg.icon} {statusCfg.label}
          </span>
        );
      },
    },
    {
      key: "tries",
      header: "Tries",
      renderCell: (entry) => <span className="text-(--t-2)">{entry.attempts}</span>,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      renderCell: (entry) => (
        <div className="flex justify-end gap-1.5">
          <button
            type="button"
            onClick={() => loadDetail(entry.id)}
            title="View details"
            className="inline-flex h-8 w-8 items-center justify-center rounded-(--r-sm) border-0 bg-white text-(--t-2) transition-colors hover:border-(--purple) hover:text-(--purple)"
          >
            <Eye size={14} />
          </button>
          {entry.status !== "sent" && (
            <button
              type="button"
              onClick={() => handleResend(entry.id)}
              disabled={isResending}
              title="Resend"
              className="inline-flex h-8 w-8 items-center justify-center rounded-(--r-sm) border-0 bg-white text-(--t-2) transition-colors hover:border-(--warn) hover:text-(--warn) disabled:opacity-40"
            >
              <RotateCcw size={14} />
            </button>
          )}
        </div>
      ),
    },
  ];

  /* Loading / guard */
  const { setHeader } = useWorkspacePageHeader();
  useEffect(() => {
    setHeader({
      actions: isAdmin ? (
        <>
          <label className="flex items-center gap-2">
            <ToggleSwitch
              checked={autoRefresh}
              onChange={setAutoRefresh}
              aria-label="Auto-refresh"
            />
            <span className={`${MICRO_LABEL} max-sm:hidden`}>Auto-refresh</span>
          </label>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void handleExport()}
            disabled={controlsDisabled}
          >
            <Download size={14} />
            <span className="max-sm:hidden">Export</span>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              void loadEmails();
              void loadStats();
            }}
            disabled={controlsDisabled}
            aria-label="Refresh"
            title="Refresh"
            className="h-8 w-8 p-0"
          >
            <RefreshCcw size={14} className={isLoading ? "animate-spin" : ""} />
          </Button>
        </>
      ) : null,
    });
    return () => setHeader(null);
  }, [
    autoRefresh,
    controlsDisabled,
    handleExport,
    isAdmin,
    isLoading,
    loadEmails,
    loadStats,
    setHeader,
  ]);

  if (isGuardLoading) {
    return <AdminTableSkeleton rows={10} columns={6} />;
  }

  if (!isAdmin) {
    return <AdminInlineError message="Admin privileges required to view the email outbox." />;
  }

  return (
    <>
      {/* Header */}
      <DashboardPageIntro icon={Mail} title="Email outbox">
        Transactional email delivery monitoring
      </DashboardPageIntro>

      {/* Stats cards */}
      {stats && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard title="Total emails" value={stats.total.toLocaleString()} />
          <StatCard
            title="Sent"
            value={stats.sent.toLocaleString()}
            subtitle={`${stats.delivery_rate}% delivery rate`}
          />
          <StatCard title="Pending / retry" value={`${stats.pending + stats.retry}`} />
          <StatCard
            title="Failed"
            value={stats.failed.toLocaleString()}
            subtitle={`${stats.avg_attempts} avg attempts`}
          />
        </div>
      )}

      {/* Error banner */}
      {error && <AdminInlineError message={error} onRetry={loadEmails} />}

      {/* Filters */}
      <div className={WSEC}>
        <div className="flex flex-col gap-3 md:flex-row md:flex-wrap">
          <div className="relative flex-1 md:min-w-[220px]">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-(--t-3)" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by recipient, subject, correlation ID..."
              className={`${WINPUT_SM} w-full pl-8`}
            />
          </div>

          <NativeSelect
            variant="auth"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="h-8 w-auto text-[12.5px] md:min-w-[140px]"
            aria-label="Status filter"
          >
            <option value="">All Statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s.charAt(0).toUpperCase() + s.slice(1)}
              </option>
            ))}
          </NativeSelect>

          <NativeSelect
            variant="auth"
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="h-8 w-auto text-[12.5px] md:min-w-[180px]"
            aria-label="Category filter"
          >
            <option value="">All Categories</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c.replace(/_/g, " ")}
              </option>
            ))}
          </NativeSelect>

          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className={WINPUT_SM}
            aria-label="From date"
          />
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className={WINPUT_SM}
            aria-label="To date"
          />

          <label className="flex items-center gap-2 px-1">
            <input
              type="checkbox"
              checked={hasErrorFilter}
              onChange={(e) => setHasErrorFilter(e.target.checked)}
              className="h-[17px] w-[17px] rounded-[5px] border-0 bg-[#EEF1F6] accent-(--ink)"
            />
            <span className={`${MICRO_LABEL} text-(--bad)`}>Errors only</span>
          </label>

          {(searchQuery ||
            statusFilter ||
            categoryFilter ||
            dateFrom ||
            dateTo ||
            hasErrorFilter) && (
            <button
              onClick={() => {
                setSearchQuery("");
                setStatusFilter("");
                setCategoryFilter("");
                setDateFrom("");
                setDateTo("");
                setHasErrorFilter(false);
              }}
              className="flex items-center gap-1.5 rounded-(--r-sm) border-0 bg-white px-3 py-2 text-xs font-medium text-(--t-2) transition-colors hover:text-(--t-1)"
            >
              <X size={14} />
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Table */}
      <SignalDataTable
        columns={columns}
        rows={emails}
        rowKey={(entry) => entry.id}
        emptyLabel={isLoading ? "Loading emails..." : "No emails match current filters."}
        tools={
          <NativeSelect
            variant="auth"
            value={pageSize}
            onChange={(e) => setPageSize(Number(e.target.value))}
            className="h-8 w-auto text-[12.5px]"
            aria-label="Rows per page"
          >
            <option value={25}>25 / page</option>
            <option value={50}>50 / page</option>
            <option value={100}>100 / page</option>
            <option value={200}>200 / page</option>
          </NativeSelect>
        }
        metaLabel={`${emails.length} / ${total} emails`}
        pageSize={pageSize}
        footer={
          <>
            <span className="font-(family-name:--mono) text-[11px] text-(--t-3)">
              Page {page} of {totalPages}
            </span>
            <nav className="ms-auto inline-flex items-center gap-1" aria-label="Pagination">
              <button
                type="button"
                onClick={() => setPage((prev) => Math.max(1, prev - 1))}
                disabled={page <= 1 || controlsDisabled}
                aria-label="Previous page"
                className={PAGER_BTN}
              >
                <ChevronLeft size={14} />
              </button>
              <button
                type="button"
                onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))}
                disabled={page >= totalPages || controlsDisabled}
                aria-label="Next page"
                className={PAGER_BTN}
              >
                <ChevronRight size={14} />
              </button>
            </nav>
          </>
        }
      />

      {/* Detail modal */}
      {(selectedId !== null || detailLoading) && (
        <DetailModal
          detail={detail}
          isLoading={detailLoading}
          onClose={() => {
            setSelectedId(null);
            setDetail(null);
          }}
          onResend={handleResend}
          isResending={isResending}
        />
      )}
    </>
  );
}
