"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Search,
  ChevronLeft,
  ChevronRight,
  RefreshCcw,
  Download,
  X,
  Shield,
  Eye,
  Activity,
  Users,
  Settings,
  Database,
  FileText,
  Zap,
  ScrollText,
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
import { NativeSelect } from "@/components/ui/native-select";
import { AdminInlineError } from "@/components/admin/AdminInlineError";
import { AdminTableSkeleton } from "@/components/admin/AdminTableSkeleton";
import { getTierShort } from "@/constants/tiers";

/* -------------------------------------------------------------------------- */
/*  Types                                                                      */
/* -------------------------------------------------------------------------- */

type ActionLogEntry = {
  id: number;
  admin_user_id: number | null;
  admin_email: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
};

type ActionLogPage = {
  items: ActionLogEntry[];
  total: number;
  page: number;
  page_size: number;
};

type ActionLogSummary = {
  total_actions: number;
  actions_last_24h: number;
  actions_last_7d: number;
  top_actions: { label: string; count: number }[];
  top_actors: { label: string; count: number }[];
  top_target_types: { label: string; count: number }[];
};

type AdminAuditEntry = {
  id: number;
  user_id: number;
  user_email: string;
  url: string;
  audit_target_type: string | null;
  target_name: string | null;
  target_url: string | null;
  geo_score: number;
  seo_score: number;
  aeo_score: number;
  provider: string | null;
  tier: string | null;
  requested_tier: string | null;
  grounding_profile: string | null;
  dual_track_grounding_enabled: boolean;
  fallback_reason: string | null;
  track_a_claim_count: number | null;
  track_b_claim_count: number | null;
  dual_track_rollout_mode: string | null;
  dual_track_execution_mode: string | null;
  created_at: string;
  sanitized_at: string | null;
  has_screenshot: boolean;
};

type AdminAuditPage = {
  audits: AdminAuditEntry[];
  total: number;
  page: number;
  page_size: number;
};

type AuditExecutionFilters = {
  urlContains: string;
  groundingProfile: string;
  dualTrackEnabled: "all" | "enabled" | "disabled";
  fallbackReason: string;
};

/* -------------------------------------------------------------------------- */
/*  Constants                                                                  */
/* -------------------------------------------------------------------------- */

const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const MONO_META = MICRO_LABEL.replace("uppercase ", "");
const WSTAT = "rounded-(--r) border border-(--line) bg-(--panel) px-4 py-3";
const WSTAT_VALUE =
  "font-(family-name:--disp) text-[20px] font-bold leading-none tracking-[-0.02em] text-(--t-1)";
const WSEC = "rounded-(--r) border border-(--line) bg-(--panel) px-[22px] py-[18px]";
const WINPUT_SM =
  "field-focus-ring h-8 rounded-(--r-md) border border-(--line) bg-(--paper) px-[10px] text-[12.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6]";
const CHIP =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";
const PAGER_BTN =
  "inline-flex h-8 min-w-8 items-center justify-center rounded-(--r-sm) px-2 text-(--t-2) hover:bg-(--line-2) hover:text-(--t-1) disabled:opacity-40";

const ACTION_CATEGORIES: Record<string, { label: string; icon: React.ReactNode }> = {
  user: { label: "User", icon: <Users size={12} /> },
  admin: { label: "Admin", icon: <Shield size={12} /> },
  audit: { label: "Audit", icon: <Eye size={12} /> },
  billing: { label: "Billing", icon: <Zap size={12} /> },
  cache: { label: "Cache", icon: <Database size={12} /> },
  cms: { label: "CMS", icon: <FileText size={12} /> },
  data: { label: "Data", icon: <Database size={12} /> },
  fallback: { label: "Ops", icon: <Settings size={12} /> },
};

const CATEGORY_CHIP: Record<string, string> = {
  user: `${CHIP} text-(--purple) bg-(--purple-s)`,
  admin: `${CHIP} text-(--warn) bg-(--warn-s)`,
  audit: `${CHIP} text-(--purple) bg-(--purple-s)`,
  billing: `${CHIP} text-(--good) bg-(--good-s)`,
  cache: `${CHIP} text-(--purple) bg-(--purple-s)`,
  cms: `${CHIP} text-(--bad) bg-(--bad-s)`,
  data: `${CHIP} text-(--warn) bg-(--warn-s)`,
  fallback: `${CHIP} text-(--warn) bg-(--warn-s)`,
  default: `${CHIP} text-(--t-2) bg-(--line-2)`,
};

const TARGET_TYPES = [
  "user",
  "audit",
  "billing",
  "billing_config",
  "cache",
  "settings",
  "operations",
  "retention",
  "cms_article",
  "cms_case_study",
];

const GROUNDING_PROFILES = [
  "shadow_dual_track",
  "single_track_fallback",
  "legacy_single_track",
  "utc_unavailable_fallback",
];

const defaultAuditFilters: AuditExecutionFilters = {
  urlContains: "",
  groundingProfile: "",
  dualTrackEnabled: "all",
  fallbackReason: "",
};

/* -------------------------------------------------------------------------- */
/*  Helpers                                                                    */
/* -------------------------------------------------------------------------- */

function getCategoryForAction(action: string) {
  const prefix = action.split("_")[0];
  return ACTION_CATEGORIES[prefix] ?? { label: prefix, icon: <Activity size={12} /> };
}

function formatActionLabel(action: string): string {
  return action.replace(/_/g, " ");
}

function formatAuditLabel(value: string | null | undefined): string {
  if (!value) return "-";
  return value.replace(/_/g, " ");
}

function getGroundingProfileChip(profile: string | null): string {
  if (!profile) return `${CHIP} text-(--t-2) bg-(--line-2)`;
  if (profile === "shadow_dual_track") return `${CHIP} text-(--purple) bg-(--purple-s)`;
  if (profile.includes("fallback")) return `${CHIP} text-(--warn) bg-(--warn-s)`;
  return `${CHIP} text-(--purple) bg-(--purple-s)`;
}

/* -------------------------------------------------------------------------- */
/*  Detail Modal                                                               */
/* -------------------------------------------------------------------------- */

function DetailModal({ entry, onClose }: { entry: ActionLogEntry | null; onClose: () => void }) {
  const titleId = React.useId();
  if (!entry) return null;

  return (
    <Modal open onClose={onClose} title="Action details" ariaLabelledby={titleId}>
      <div className="mb-5 flex items-start justify-between">
        <div>
          <h2
            id={titleId}
            className="m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)"
          >
            Action details
          </h2>
          <p className={`${MONO_META} mt-1`}>Log #{entry.id}</p>
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          className="flex h-8 w-8 items-center justify-center rounded-(--r-sm) border border-(--line) bg-(--panel) text-(--t-2) transition-colors hover:text-(--t-1)"
        >
          <X size={16} />
        </button>
      </div>

      <div className="max-h-[70vh] space-y-4 overflow-y-auto">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className={`${MICRO_LABEL} mb-1`}>Action</p>
            <p className="text-sm font-semibold text-(--t-1)">{formatActionLabel(entry.action)}</p>
          </div>
          <div>
            <p className={`${MICRO_LABEL} mb-1`}>Admin</p>
            <p className="text-sm font-semibold text-(--t-1)">{entry.admin_email ?? "System"}</p>
          </div>
          <div>
            <p className={`${MICRO_LABEL} mb-1`}>Target type</p>
            <p className="text-sm font-semibold text-(--t-1)">{entry.target_type ?? "-"}</p>
          </div>
          <div>
            <p className={`${MICRO_LABEL} mb-1`}>Target ID</p>
            <p className="font-(family-name:--mono) text-sm font-semibold text-(--t-1)">
              {entry.target_id ?? "-"}
            </p>
          </div>
          <div className="col-span-2">
            <p className={`${MICRO_LABEL} mb-1`}>Timestamp</p>
            <p className="text-sm font-semibold text-(--t-1)">
              <ClientSafeDate date={entry.created_at} format="datetime" />
            </p>
          </div>
        </div>

        {entry.metadata && Object.keys(entry.metadata).length > 0 && (
          <div>
            <p className={`${MICRO_LABEL} mb-2`}>Metadata</p>
            <div className="overflow-x-auto rounded-(--r-md) border border-(--line) bg-(--paper) p-4">
              <pre className="whitespace-pre-wrap font-(family-name:--mono) text-xs text-(--t-2)">
                {JSON.stringify(entry.metadata, null, 2)}
              </pre>
            </div>
          </div>
        )}
      </div>

      <div className="mt-5 flex justify-end border-t border-(--line-2) pt-4">
        <Button variant="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>
    </Modal>
  );
}

/* -------------------------------------------------------------------------- */
/*  Summary Cards                                                              */
/* -------------------------------------------------------------------------- */

function SummaryCard({ title, value }: { title: string; value: string }) {
  return (
    <div className={WSTAT}>
      <span className={WSTAT_VALUE}>{value}</span>
      <span className={MICRO_LABEL}>{title}</span>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Main Page                                                                  */
/* -------------------------------------------------------------------------- */

export default function AuditTrailPage() {
  const { getToken, isSignedIn } = useAuth();
  const { isAdmin, isLoading: isGuardLoading } = useAdminAccess();

  /* Data state */
  const [logs, setLogs] = useState<ActionLogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<ActionLogSummary | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [auditExecutions, setAuditExecutions] = useState<AdminAuditEntry[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditIsLoading, setAuditIsLoading] = useState(false);
  const [auditError, setAuditError] = useState("");

  /* Pagination */
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [auditPage, setAuditPage] = useState(1);
  const [auditPageSize, setAuditPageSize] = useState(25);

  /* Filters */
  const [searchQuery, setSearchQuery] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const [targetTypeFilter, setTargetTypeFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [auditFilters, setAuditFilters] = useState<AuditExecutionFilters>(defaultAuditFilters);

  /* Modal */
  const [selectedEntry, setSelectedEntry] = useState<ActionLogEntry | null>(null);

  const debouncedSearch = useDebounce(searchQuery, 400);
  const debouncedAuditFilters = useDebounce(auditFilters, 400);
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const auditTotalPages = Math.max(1, Math.ceil(auditTotal / auditPageSize));
  const controlsDisabled = isLoading || !isAdmin;
  const auditControlsDisabled = auditIsLoading || !isAdmin;

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) throw new Error("You must be signed in to access admin data.");
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  /* Fetch logs */
  const loadLogs = useCallback(async () => {
    if (!isSignedIn) return;
    setIsLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      });
      if (debouncedSearch.trim()) params.set("search", debouncedSearch.trim());
      if (actionFilter) params.set("action", actionFilter);
      if (targetTypeFilter) params.set("target_type", targetTypeFilter);
      if (dateFrom) params.set("date_from", dateFrom);
      if (dateTo) params.set("date_to", dateTo);

      const response = await fetch(`/api/admin/action-logs?${params.toString()}`, { headers });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load action logs.");
      }
      const payload = (await response.json()) as ActionLogPage;
      setLogs(payload.items);
      setTotal(payload.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load action logs.");
    } finally {
      setIsLoading(false);
    }
  }, [
    getAuthHeaders,
    isSignedIn,
    page,
    pageSize,
    debouncedSearch,
    actionFilter,
    targetTypeFilter,
    dateFrom,
    dateTo,
  ]);

  /* Fetch summary */
  const loadSummary = useCallback(async () => {
    if (!isSignedIn) return;
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/admin/action-logs/summary", { headers });
      if (response.ok) {
        const payload = (await response.json()) as ActionLogSummary;
        setSummary(payload);
      }
    } catch {
      /* non-critical, summary is supplementary */
    }
  }, [getAuthHeaders, isSignedIn]);

  const loadAuditExecutions = useCallback(async () => {
    if (!isSignedIn) return;
    setAuditIsLoading(true);
    setAuditError("");
    try {
      const headers = await getAuthHeaders();
      const params = new URLSearchParams({
        page: String(auditPage),
        page_size: String(auditPageSize),
      });
      if (debouncedAuditFilters.urlContains.trim()) {
        params.set("url_contains", debouncedAuditFilters.urlContains.trim());
      }
      if (debouncedAuditFilters.groundingProfile) {
        params.set("grounding_profile", debouncedAuditFilters.groundingProfile);
      }
      if (debouncedAuditFilters.dualTrackEnabled === "enabled") {
        params.set("dual_track_grounding_enabled", "true");
      }
      if (debouncedAuditFilters.dualTrackEnabled === "disabled") {
        params.set("dual_track_grounding_enabled", "false");
      }
      if (debouncedAuditFilters.fallbackReason.trim()) {
        params.set("fallback_reason", debouncedAuditFilters.fallbackReason.trim());
      }

      const response = await fetch(`/api/admin/audits?${params.toString()}`, { headers });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load audit executions.");
      }
      const payload = (await response.json()) as AdminAuditPage;
      setAuditExecutions(payload.audits);
      setAuditTotal(payload.total);
    } catch (err) {
      setAuditError(err instanceof Error ? err.message : "Unable to load audit executions.");
    } finally {
      setAuditIsLoading(false);
    }
  }, [auditPage, auditPageSize, debouncedAuditFilters, getAuthHeaders, isSignedIn]);

  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  useEffect(() => {
    loadAuditExecutions();
  }, [loadAuditExecutions]);

  /* Reset page on filter change */
  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, actionFilter, targetTypeFilter, dateFrom, dateTo, pageSize]);

  useEffect(() => {
    setAuditPage(1);
  }, [debouncedAuditFilters, auditPageSize]);

  /* CSV Export */
  const handleExport = useCallback(async () => {
    if (!isSignedIn) return;
    try {
      const headers = await getAuthHeaders();
      const params = new URLSearchParams({
        page: "1",
        page_size: "10000",
      });
      if (debouncedSearch.trim()) params.set("search", debouncedSearch.trim());
      if (actionFilter) params.set("action", actionFilter);
      if (targetTypeFilter) params.set("target_type", targetTypeFilter);
      if (dateFrom) params.set("date_from", dateFrom);
      if (dateTo) params.set("date_to", dateTo);

      const response = await fetch(`/api/admin/action-logs?${params.toString()}`, { headers });
      if (!response.ok) return;
      const payload = (await response.json()) as ActionLogPage;

      const csvRows = [
        ["ID", "Timestamp", "Admin", "Action", "Target Type", "Target ID", "Metadata"].join(","),
        ...payload.items.map((item) =>
          [
            item.id,
            item.created_at,
            item.admin_email ?? "System",
            item.action,
            item.target_type ?? "",
            item.target_id ?? "",
            item.metadata ? JSON.stringify(item.metadata).replace(/,/g, ";") : "",
          ].join(",")
        ),
      ].join("\n");

      const blob = new Blob([csvRows], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `admin-action-logs-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      /* export is best-effort */
    }
  }, [
    getAuthHeaders,
    isSignedIn,
    debouncedSearch,
    actionFilter,
    targetTypeFilter,
    dateFrom,
    dateTo,
  ]);

  /* Distinct action strings for dropdown (derived from summary) */
  const actionOptions = useMemo(() => {
    if (!summary) return [];
    return summary.top_actions.map((a) => a.label).sort();
  }, [summary]);

  const logColumns: SignalDataTableColumn<ActionLogEntry>[] = [
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
      key: "admin",
      header: "Admin",
      renderCell: (entry) => (
        <span className="font-semibold text-(--t-1)">{entry.admin_email ?? "System"}</span>
      ),
    },
    {
      key: "action",
      header: "Action",
      renderCell: (entry) => {
        const prefix = entry.action.split("_")[0];
        const category = getCategoryForAction(entry.action);
        const chip = CATEGORY_CHIP[prefix] ?? CATEGORY_CHIP.default;
        return (
          <span className={chip}>
            {category.icon}
            {formatActionLabel(entry.action)}
          </span>
        );
      },
    },
    {
      key: "target_type",
      header: "Target type",
      renderCell: (entry) => <span className="text-(--t-2)">{entry.target_type ?? "-"}</span>,
    },
    {
      key: "target_id",
      header: "Target ID",
      renderCell: (entry) => (
        <span className="font-(family-name:--mono) text-xs text-(--t-3)">
          {entry.target_id ?? "-"}
        </span>
      ),
    },
    {
      key: "view",
      header: "",
      align: "right",
      renderCell: (entry) => (
        <button
          type="button"
          onClick={() => setSelectedEntry(entry)}
          aria-label="View log details"
          className="inline-flex h-8 w-8 items-center justify-center rounded-(--r-sm) border border-(--line) bg-(--panel) text-(--t-2) transition-colors hover:border-(--purple) hover:text-(--purple)"
        >
          <Eye size={14} />
        </button>
      ),
    },
  ];

  const auditColumns: SignalDataTableColumn<AdminAuditEntry>[] = [
    {
      key: "audit",
      header: "Audit",
      renderCell: (audit) => (
        <div className="space-y-1">
          <Link
            href={`/admin/audit-application/${audit.id}`}
            className="font-semibold text-(--t-1) transition-colors hover:text-(--purple)"
          >
            #{audit.id}
          </Link>
          <p className={MICRO_LABEL}>
            <ClientSafeDate date={audit.created_at} format="datetime" />
          </p>
        </div>
      ),
    },
    {
      key: "target",
      header: "Target",
      renderCell: (audit) => {
        const targetLabel = audit.target_name ?? audit.target_url ?? audit.url;
        return (
          <div className="space-y-1">
            <p className="font-semibold text-(--t-1)">{audit.user_email}</p>
            <p className="text-xs text-(--t-2)">{targetLabel}</p>
            <p className={MONO_META}>{formatAuditLabel(audit.audit_target_type)}</p>
          </div>
        );
      },
    },
    {
      key: "grounding",
      header: "Grounding",
      renderCell: (audit) => (
        <div className="flex flex-wrap gap-2">
          <span className={getGroundingProfileChip(audit.grounding_profile)}>
            {formatAuditLabel(audit.grounding_profile)}
          </span>
          <span
            className={`${CHIP} ${
              audit.dual_track_grounding_enabled
                ? "text-(--good) bg-(--good-s)"
                : "text-(--t-2) bg-(--line-2)"
            }`}
          >
            {audit.dual_track_grounding_enabled ? "Dual-track on" : "Dual-track off"}
          </span>
        </div>
      ),
    },
    {
      key: "mode",
      header: "Requested mode",
      renderCell: (audit) => (
        <div className="space-y-1">
          <p className={`${MONO_META} text-(--t-2)`}>
            {getTierShort(audit.requested_tier ?? audit.tier)}
          </p>
          <p className={MONO_META}>Rollout {formatAuditLabel(audit.dual_track_rollout_mode)}</p>
          <p className={MONO_META}>Exec {formatAuditLabel(audit.dual_track_execution_mode)}</p>
        </div>
      ),
    },
    {
      key: "claims",
      header: "Claims",
      renderCell: (audit) => (
        <div className="space-y-1">
          <p className="text-xs font-semibold text-(--t-1)">
            Track A {audit.track_a_claim_count ?? 0}
          </p>
          <p className="text-xs font-semibold text-(--t-1)">
            Track B {audit.track_b_claim_count ?? 0}
          </p>
        </div>
      ),
    },
    {
      key: "fallback",
      header: "Fallback",
      renderCell: (audit) =>
        audit.fallback_reason ? (
          <span className={`${CHIP} text-(--warn) bg-(--warn-s)`}>
            {formatAuditLabel(audit.fallback_reason)}
          </span>
        ) : (
          <span className="text-xs font-semibold text-(--t-3)">-</span>
        ),
    },
  ];

  /* Loading / guard states */
  const { setHeader } = useWorkspacePageHeader();
  useEffect(() => {
    setHeader({
      actions: isAdmin ? (
        <>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void handleExport()}
            disabled={controlsDisabled}
          >
            <Download size={14} />
            <span className="max-sm:hidden">Export CSV</span>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              void loadLogs();
              void loadSummary();
              void loadAuditExecutions();
            }}
            disabled={controlsDisabled || auditControlsDisabled}
            aria-label="Refresh"
            title="Refresh"
            className="h-8 w-8 p-0"
          >
            <RefreshCcw size={14} className={isLoading || auditIsLoading ? "animate-spin" : ""} />
          </Button>
        </>
      ) : null,
    });
    return () => setHeader(null);
  }, [
    auditControlsDisabled,
    auditIsLoading,
    controlsDisabled,
    handleExport,
    isAdmin,
    isLoading,
    loadAuditExecutions,
    loadLogs,
    loadSummary,
    setHeader,
  ]);

  if (isGuardLoading) {
    return <AdminTableSkeleton rows={10} columns={5} />;
  }

  if (!isAdmin) {
    return <AdminInlineError message="Admin privileges required to view the audit trail." />;
  }

  return (
    <>
      {/* Header */}
      <DashboardPageIntro icon={ScrollText} title="Audit trail">
        Log of all administrative actions
      </DashboardPageIntro>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <SummaryCard title="Total actions" value={summary.total_actions.toLocaleString()} />
          <SummaryCard title="Last 24 hours" value={summary.actions_last_24h.toLocaleString()} />
          <SummaryCard title="Last 7 days" value={summary.actions_last_7d.toLocaleString()} />
        </div>
      )}

      {/* Error banner */}
      {error && <AdminInlineError message={error} onRetry={loadLogs} />}

      {/* Filters */}
      <div className={WSEC}>
        <div className="flex flex-col gap-3 md:flex-row md:flex-wrap">
          <div className="relative flex-1 md:min-w-[220px]">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-(--t-3)" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search actions, targets..."
              className={`${WINPUT_SM} w-full pl-8`}
            />
          </div>

          <NativeSelect
            variant="auth"
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
            className="h-8 w-auto text-[12.5px] md:min-w-[160px]"
          >
            <option value="">All Actions</option>
            {actionOptions.map((a) => (
              <option key={a} value={a}>
                {formatActionLabel(a)}
              </option>
            ))}
          </NativeSelect>

          <NativeSelect
            variant="auth"
            value={targetTypeFilter}
            onChange={(e) => setTargetTypeFilter(e.target.value)}
            className="h-8 w-auto text-[12.5px] md:min-w-[160px]"
          >
            <option value="">All Targets</option>
            {TARGET_TYPES.map((t) => (
              <option key={t} value={t}>
                {t.replace(/_/g, " ")}
              </option>
            ))}
          </NativeSelect>

          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className={WINPUT_SM}
            placeholder="From"
            aria-label="From date"
          />
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className={WINPUT_SM}
            placeholder="To"
            aria-label="To date"
          />

          {(searchQuery || actionFilter || targetTypeFilter || dateFrom || dateTo) && (
            <button
              onClick={() => {
                setSearchQuery("");
                setActionFilter("");
                setTargetTypeFilter("");
                setDateFrom("");
                setDateTo("");
              }}
              className="flex items-center gap-1.5 rounded-(--r-sm) border border-(--line) bg-(--panel) px-3 py-2 text-xs font-medium text-(--t-2) transition-colors hover:text-(--t-1)"
            >
              <X size={14} />
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Action log table */}
      <SignalDataTable
        columns={logColumns}
        rows={logs}
        rowKey={(entry) => entry.id}
        emptyLabel={isLoading ? "Loading activity logs..." : "No actions match current filters."}
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
        metaLabel={`${logs.length} / ${total} actions`}
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

      {/* Audit execution trail */}
      <div className="overflow-hidden rounded-(--r-md) border border-(--line) bg-(--panel)">
        <div className="border-b border-(--line) px-[22px] py-[18px]">
          <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)">
                Audit execution trail
              </h2>
              <p className={`${MONO_META} mt-1`}>
                Filter degraded and dual-track audit runs by runtime metadata
              </p>
            </div>
            <div className="text-right">
              <p className={MICRO_LABEL}>Matching audits</p>
              <p className="text-sm font-semibold text-(--t-1)">
                {auditExecutions.length} <span className="text-(--t-3)">/</span> {auditTotal}
              </p>
            </div>
          </div>
        </div>

        <div className="space-y-4 p-4">
          {auditError && <AdminInlineError message={auditError} onRetry={loadAuditExecutions} />}

          <div className="grid gap-3 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,0.8fr)_180px_minmax(0,1fr)_auto]">
            <div className="relative">
              <Search
                size={14}
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-(--t-3)"
              />
              <input
                aria-label="Audit URL fragment"
                type="text"
                value={auditFilters.urlContains}
                onChange={(e) =>
                  setAuditFilters((current) => ({
                    ...current,
                    urlContains: e.target.value,
                  }))
                }
                placeholder="Filter by URL or brand target..."
                className={`${WINPUT_SM} w-full pl-8`}
              />
            </div>

            <NativeSelect
              variant="auth"
              aria-label="Grounding profile filter"
              value={auditFilters.groundingProfile}
              onChange={(e) =>
                setAuditFilters((current) => ({
                  ...current,
                  groundingProfile: e.target.value,
                }))
              }
              className="h-8 w-full text-[12.5px]"
            >
              <option value="">All grounding profiles</option>
              {GROUNDING_PROFILES.map((profile) => (
                <option key={profile} value={profile}>
                  {formatAuditLabel(profile)}
                </option>
              ))}
            </NativeSelect>

            <NativeSelect
              variant="auth"
              aria-label="Dual-track enabled filter"
              value={auditFilters.dualTrackEnabled}
              onChange={(e) =>
                setAuditFilters((current) => ({
                  ...current,
                  dualTrackEnabled: e.target.value as AuditExecutionFilters["dualTrackEnabled"],
                }))
              }
              className="h-8 w-full text-[12.5px]"
            >
              <option value="all">All dual-track states</option>
              <option value="enabled">Dual-track enabled</option>
              <option value="disabled">Dual-track disabled</option>
            </NativeSelect>

            <input
              aria-label="Fallback reason filter"
              type="text"
              value={auditFilters.fallbackReason}
              onChange={(e) =>
                setAuditFilters((current) => ({
                  ...current,
                  fallbackReason: e.target.value,
                }))
              }
              placeholder="Fallback reason..."
              className={WINPUT_SM}
            />

            {(auditFilters.urlContains ||
              auditFilters.groundingProfile ||
              auditFilters.dualTrackEnabled !== "all" ||
              auditFilters.fallbackReason) && (
              <button
                onClick={() => {
                  setAuditFilters(defaultAuditFilters);
                }}
                className="flex items-center justify-center gap-1.5 rounded-(--r-sm) border border-(--line) bg-(--panel) px-3 py-2 text-xs font-medium text-(--t-2) transition-colors hover:text-(--t-1)"
              >
                <X size={14} />
                Clear
              </button>
            )}
          </div>
        </div>

        <SignalDataTable
          columns={auditColumns}
          rows={auditExecutions}
          rowKey={(audit) => audit.id}
          emptyLabel={
            auditIsLoading
              ? "Loading audit executions..."
              : "No audits match current runtime filters."
          }
          className="rounded-none border-x-0 border-b-0"
          tools={
            <>
              <NativeSelect
                variant="auth"
                aria-label="Audit executions page size"
                value={auditPageSize}
                onChange={(e) => setAuditPageSize(Number(e.target.value))}
                className="h-8 w-auto text-[12.5px]"
              >
                <option value={10}>10 / page</option>
                <option value={25}>25 / page</option>
                <option value={50}>50 / page</option>
              </NativeSelect>
              <Button
                variant="ghost"
                size="sm"
                onClick={loadAuditExecutions}
                disabled={auditControlsDisabled}
                aria-label="Refresh audit executions"
              >
                <RefreshCcw size={14} className={auditIsLoading ? "animate-spin" : ""} />
              </Button>
            </>
          }
          footer={
            <>
              <span className="font-(family-name:--mono) text-[11px] text-(--t-3)">
                Page {auditPage} of {auditTotalPages}
              </span>
              <nav className="ms-auto inline-flex items-center gap-1" aria-label="Pagination">
                <button
                  type="button"
                  onClick={() => setAuditPage((current) => Math.max(1, current - 1))}
                  disabled={auditPage <= 1 || auditControlsDisabled}
                  aria-label="Previous page"
                  className={PAGER_BTN}
                >
                  <ChevronLeft size={14} />
                </button>
                <button
                  type="button"
                  onClick={() => setAuditPage((current) => Math.min(auditTotalPages, current + 1))}
                  disabled={auditPage >= auditTotalPages || auditControlsDisabled}
                  aria-label="Next page"
                  className={PAGER_BTN}
                >
                  <ChevronRight size={14} />
                </button>
              </nav>
            </>
          }
        />
      </div>

      {/* Detail modal */}
      {selectedEntry && (
        <DetailModal entry={selectedEntry} onClose={() => setSelectedEntry(null)} />
      )}
    </>
  );
}
