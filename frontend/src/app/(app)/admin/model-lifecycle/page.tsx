"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  Shield,
  Activity,
  RefreshCw,
  Check,
  Eye,
  AlertTriangle,
  CheckCircle,
  Info,
  Clock,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Filter,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { AdminGuardProvider } from "@/components/admin/AdminGuardProvider";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import SignalTabs from "@/components/signal/SignalTabs";
import Button from "@/components/ui/Button";
import { ClientSafeDate } from "@/lib/dateFormat";
import { requestJson } from "@/services/http";
import { cx } from "@/components/ui/utils";

/* ── Types ──────────────────────────────────────────────────────── */

type LifecycleAlert = {
  id: number;
  provider: string;
  alert_type: string;
  severity: "critical" | "warning" | "info";
  title: string;
  description: string;
  affected_models: string[] | null;
  details: Record<string, unknown> | null;
  status: "active" | "acknowledged" | "resolved";
  source_url: string | null;
  created_at: string;
  acknowledged_at: string | null;
  acknowledged_by_email: string | null;
  resolved_at: string | null;
};

type LifecycleSnapshot = {
  id: number;
  provider: string;
  source_url: string;
  page_type: string;
  content_hash: string;
  fetched_at: string;
  extracted_models: Record<string, unknown>[];
};

type LifecycleSource = {
  provider: string;
  url: string;
  page_type: string;
};

type LifecycleStats = {
  total: number;
  active: number;
  critical_unresolved: number;
  acknowledged: number;
  resolved: number;
  by_provider: Record<string, number>;
  by_severity: Record<string, number>;
  last_check_at: string | null;
};

type PaginatedResponse<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
};

type TabKey = "alerts" | "snapshots" | "sources";

/* ── Design tokens (inlined per ledger §2.3/§4.6) ───────────────── */

const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const MONO_META = MICRO_LABEL.replace("uppercase ", "");
const WSEC = "rounded-(--r) border border-(--line) bg-(--panel) px-[22px] py-[18px]";
const TABLE_SECTION = "overflow-hidden rounded-(--r) border border-(--line) bg-(--panel)";
const TH = `p-3 text-left ${MICRO_LABEL}`;
const TD = "p-3 text-xs text-(--t-2)";
const CHIP =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";

const CHIP_COLORS: Record<string, string> = {
  danger: "text-(--bad) bg-(--bad-s)",
  warning: "text-(--warn) bg-(--warn-s)",
  info: "text-(--purple) bg-(--purple-s)",
  success: "text-(--good) bg-(--good-s)",
  default: "text-(--t-2) bg-(--paper)",
};

function Chip({ color = "default", children }: { color?: string; children: React.ReactNode }) {
  return <span className={`${CHIP} ${CHIP_COLORS[color] ?? CHIP_COLORS.default}`}>{children}</span>;
}

/* ── Display helpers ────────────────────────────────────────────── */

const severityChipColor = (severity: LifecycleAlert["severity"]) => {
  switch (severity) {
    case "critical":
      return "danger";
    case "warning":
      return "warning";
    case "info":
      return "info";
  }
};

const severityIcon = (severity: LifecycleAlert["severity"]) => {
  switch (severity) {
    case "critical":
      return <AlertTriangle size={12} />;
    case "warning":
      return <AlertTriangle size={12} />;
    case "info":
      return <Info size={12} />;
  }
};

const statusChipColor = (status: LifecycleAlert["status"]) => {
  switch (status) {
    case "active":
      return "danger";
    case "acknowledged":
      return "warning";
    case "resolved":
      return "success";
  }
};

const ALERT_TYPE_LABELS: Record<string, string> = {
  model_appeared: "Model Appeared (Deprecations)",
  pricing_model_appeared: "Model Appeared (Pricing)",
  lifecycle_change: "Lifecycle Keywords Changed",
  model_removed: "Model Removed From Page",
  page_changed: "Page Content Updated",
};

const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI",
  google: "Google",
  anthropic: "Anthropic",
  perplexity: "Perplexity",
  bing: "Azure OpenAI",
  xai: "xAI",
  deepseek: "DeepSeek",
};

const providerLabel = (p: string) => PROVIDER_LABELS[p] || p;
const alertTypeLabel = (t: string) => ALERT_TYPE_LABELS[t] || t.replace(/_/g, " ");

/* ── Tab definitions ────────────────────────────────────────────── */

const TABS: { id: TabKey; label: string }[] = [
  { id: "alerts", label: "Alerts" },
  { id: "snapshots", label: "Snapshots" },
  { id: "sources", label: "Sources" },
];

/* ── Filter pill ────────────────────────────────────────────────── */

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={cx(
        "rounded-(--r-sm) border border-(--line) bg-(--panel) px-3 py-1.5 text-xs",
        "text-(--t-1) outline-hidden transition-colors",
        "focus:border-(--purple) focus:ring-1 focus:ring-(--purple)",
        value ? "border-(--purple) text-(--purple)" : "text-(--t-3)"
      )}
    >
      <option value="">{label}</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

/* ── Main page ──────────────────────────────────────────────────── */

export default function ModelLifecyclePage() {
  const [activeTab, setActiveTab] = useState<TabKey>("alerts");

  const [alerts, setAlerts] = useState<LifecycleAlert[]>([]);
  const [snapshots, setSnapshots] = useState<LifecycleSnapshot[]>([]);
  const [sources, setSources] = useState<LifecycleSource[]>([]);
  const [stats, setStats] = useState<LifecycleStats | null>(null);

  const [alertsPage, setAlertsPage] = useState(1);
  const [alertsTotal, setAlertsTotal] = useState(0);
  const [snapshotsPage, setSnapshotsPage] = useState(1);
  const [snapshotsTotal, setSnapshotsTotal] = useState(0);
  const pageSize = 25;

  /* ── Alert filters ──────────────────────────────────────────── */
  const [filterStatus, setFilterStatus] = useState("");
  const [filterProvider, setFilterProvider] = useState("");
  const [filterSeverity, setFilterSeverity] = useState("");
  const [snapshotProvider, setSnapshotProvider] = useState("");

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [checkRunning, setCheckRunning] = useState(false);
  const [actionInFlight, setActionInFlight] = useState<number | null>(null);

  /* ── Data loading ────────────────────────────────────────────── */

  const loadStats = useCallback(async () => {
    try {
      const data = await requestJson<LifecycleStats>({
        endpoint: "/api/v1/admin/model-lifecycle/stats",
        method: "GET",
        errorMessage: "Failed to load stats.",
      });
      setStats(data);
    } catch {
      /* non-fatal, KPIs fall back to page counts */
    }
  }, []);

  const loadAlerts = useCallback(
    async (pg = alertsPage) => {
      const params = new URLSearchParams({ page: String(pg), page_size: String(pageSize) });
      if (filterStatus) params.set("status", filterStatus);
      if (filterProvider) params.set("provider", filterProvider);
      if (filterSeverity) params.set("severity", filterSeverity);
      const data = await requestJson<PaginatedResponse<LifecycleAlert>>({
        endpoint: `/api/v1/admin/model-lifecycle/alerts?${params}`,
        method: "GET",
        errorMessage: "Failed to load lifecycle alerts.",
      });
      setAlerts(data.items);
      setAlertsTotal(data.total);
    },
    [alertsPage, pageSize, filterStatus, filterProvider, filterSeverity]
  );

  const loadSnapshots = useCallback(
    async (pg = snapshotsPage) => {
      const params = new URLSearchParams({ page: String(pg), page_size: String(pageSize) });
      if (snapshotProvider) params.set("provider", snapshotProvider);
      const data = await requestJson<PaginatedResponse<LifecycleSnapshot>>({
        endpoint: `/api/v1/admin/model-lifecycle/snapshots?${params}`,
        method: "GET",
        errorMessage: "Failed to load lifecycle snapshots.",
      });
      setSnapshots(data.items);
      setSnapshotsTotal(data.total);
    },
    [snapshotsPage, pageSize, snapshotProvider]
  );

  const loadSources = useCallback(async () => {
    const data = await requestJson<LifecycleSource[]>({
      endpoint: "/api/v1/admin/model-lifecycle/sources",
      method: "GET",
      errorMessage: "Failed to load lifecycle sources.",
    });
    setSources(data);
  }, []);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      await Promise.all([loadStats(), loadAlerts(), loadSnapshots(), loadSources()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load model lifecycle data.");
    } finally {
      setLoading(false);
    }
  }, [loadStats, loadAlerts, loadSnapshots, loadSources]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  useEffect(() => {
    if (!loading) {
      setAlertsPage(1);
      loadAlerts(1);
    }
  }, [filterStatus, filterProvider, filterSeverity]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!loading) loadAlerts(alertsPage);
  }, [alertsPage]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!loading) {
      setSnapshotsPage(1);
      loadSnapshots(1);
    }
  }, [snapshotProvider]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!loading) loadSnapshots(snapshotsPage);
  }, [snapshotsPage]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ── Actions ─────────────────────────────────────────────────── */

  const handleRunCheck = async () => {
    setCheckRunning(true);
    try {
      const result = await requestJson<Record<string, number>>({
        endpoint: "/api/v1/admin/model-lifecycle/check",
        method: "POST",
        errorMessage: "Failed to trigger lifecycle check.",
      });
      const msg = `Check complete: ${result.sources_checked ?? 0} sources, ${result.pages_changed ?? 0} changed, ${result.alerts_created ?? 0} new alerts`;
      toast.success(msg);
      await Promise.all([loadAlerts(), loadStats()]);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Check failed.");
    } finally {
      setCheckRunning(false);
    }
  };

  const handleAcknowledge = async (alertId: number) => {
    setActionInFlight(alertId);
    try {
      await requestJson<Record<string, string>>({
        endpoint: `/api/v1/admin/model-lifecycle/alerts/${alertId}/ack`,
        method: "PATCH",
        errorMessage: "Failed to acknowledge alert.",
      });
      toast.success("Alert acknowledged");
      await Promise.all([loadAlerts(), loadStats()]);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Acknowledgment failed.");
    } finally {
      setActionInFlight(null);
    }
  };

  const handleResolve = async (alertId: number) => {
    setActionInFlight(alertId);
    try {
      await requestJson<Record<string, string>>({
        endpoint: `/api/v1/admin/model-lifecycle/alerts/${alertId}/resolve`,
        method: "PATCH",
        errorMessage: "Failed to resolve alert.",
      });
      toast.success("Alert resolved");
      await Promise.all([loadAlerts(), loadStats()]);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Resolve failed.");
    } finally {
      setActionInFlight(null);
    }
  };

  /* ── KPI from stats (server-wide) ───────────────────────────── */

  const activeCount = stats?.active ?? alerts.filter((a) => a.status === "active").length;
  const criticalCount =
    stats?.critical_unresolved ??
    alerts.filter((a) => a.severity === "critical" && a.status !== "resolved").length;

  /* ── Render ──────────────────────────────────────────────────── */

  return (
    <AdminGuardProvider>
      <DashboardPageIntro icon={Shield} title="Model lifecycle monitoring">
        Track AI provider deprecations, pricing changes, and model status updates across 7
        providers.
      </DashboardPageIntro>

      {/* KPI bar */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className={`${WSEC} flex items-center gap-3 !p-4`}>
          <div
            className={cx(
              "flex h-10 w-10 shrink-0 items-center justify-center rounded-(--r-md)",
              activeCount > 0 ? "bg-(--bad-s) text-(--bad)" : "bg-(--good-s) text-(--good)"
            )}
          >
            {activeCount > 0 ? <AlertTriangle size={18} /> : <CheckCircle size={18} />}
          </div>
          <div>
            <p className={MICRO_LABEL}>Active alerts</p>
            <p className="font-(family-name:--disp) text-xl font-bold text-(--t-1)">
              {activeCount}
            </p>
          </div>
        </div>

        <div className={`${WSEC} flex items-center gap-3 !p-4`}>
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-(--r-md) bg-(--bad-s) text-(--bad)">
            <AlertTriangle size={18} />
          </div>
          <div>
            <p className={MICRO_LABEL}>Critical</p>
            <p className="font-(family-name:--disp) text-xl font-bold text-(--t-1)">
              {criticalCount}
            </p>
          </div>
        </div>

        <div className={`${WSEC} flex items-center gap-3 !p-4`}>
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-(--r-md) bg-(--paper) text-(--purple)">
            <Activity size={18} />
          </div>
          <div>
            <p className={MICRO_LABEL}>Tracked sources</p>
            <p className="font-(family-name:--disp) text-xl font-bold text-(--t-1)">
              {sources.length}
            </p>
          </div>
        </div>

        <div className={`${WSEC} flex items-center gap-3 !p-4`}>
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-(--r-md) bg-(--paper) text-(--t-3)">
            <Clock size={18} />
          </div>
          <div>
            <p className={MICRO_LABEL}>Last check</p>
            <p className="text-sm font-semibold text-(--t-1)">
              {stats?.last_check_at ? (
                <ClientSafeDate date={stats.last_check_at} format="datetime" />
              ) : (
                <span className="text-(--t-3)">Never</span>
              )}
            </p>
          </div>
        </div>
      </div>

      {/* Tabs + tab-scoped action */}
      <div className="flex items-center justify-between gap-4">
        <SignalTabs
          tabs={TABS}
          activeId={activeTab}
          onChange={(id) => setActiveTab(id as TabKey)}
        />

        {activeTab === "alerts" && (
          <Button
            variant="outline"
            size="sm"
            loading={checkRunning}
            loadingText="Checking..."
            onClick={handleRunCheck}
          >
            <RefreshCw size={14} />
            Run check now
          </Button>
        )}
      </div>

      {/* Tab content */}
      {loading ? (
        <div className={`${WSEC} space-y-3 py-6`}>
          <div className="skel h-6 w-48" />
          <div className="skel h-10 w-full" />
          <div className="skel h-10 w-full" />
          <div className="skel h-10 w-full" />
        </div>
      ) : error ? (
        <div className={`${WSEC} flex flex-col items-center gap-4 py-12 text-center`}>
          <AlertTriangle size={32} className="text-(--bad)" />
          <p className="text-sm font-semibold text-(--t-1)">{error}</p>
          <Button variant="outline" size="sm" onClick={loadAll}>
            <RefreshCw size={14} />
            Retry
          </Button>
        </div>
      ) : (
        <>
          {activeTab === "alerts" && (
            <AlertsTab
              alerts={alerts}
              actionInFlight={actionInFlight}
              onAcknowledge={handleAcknowledge}
              onResolve={handleResolve}
              page={alertsPage}
              pageSize={pageSize}
              total={alertsTotal}
              onPageChange={setAlertsPage}
              filterStatus={filterStatus}
              filterProvider={filterProvider}
              filterSeverity={filterSeverity}
              onFilterStatus={setFilterStatus}
              onFilterProvider={setFilterProvider}
              onFilterSeverity={setFilterSeverity}
            />
          )}
          {activeTab === "snapshots" && (
            <SnapshotsTab
              snapshots={snapshots}
              page={snapshotsPage}
              pageSize={pageSize}
              total={snapshotsTotal}
              onPageChange={setSnapshotsPage}
              filterProvider={snapshotProvider}
              onFilterProvider={setSnapshotProvider}
            />
          )}
          {activeTab === "sources" && <SourcesTab sources={sources} />}
        </>
      )}
    </AdminGuardProvider>
  );
}

/* ── Pagination controls ─────────────────────────────────────────── */

function PaginationBar({
  page,
  pageSize,
  total,
  onPageChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (p: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) return null;
  return (
    <div className="flex items-center justify-between border-t border-(--line) px-4 py-3">
      <p className={MONO_META}>
        Showing {(page - 1) * pageSize + 1}-{Math.min(page * pageSize, total)} of {total}
      </p>
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          <ChevronLeft size={14} />
          Prev
        </Button>
        <span className="font-(family-name:--mono) text-xs font-semibold text-(--t-2)">
          {page} / {totalPages}
        </span>
        <Button
          variant="ghost"
          size="sm"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
        >
          Next
          <ChevronRight size={14} />
        </Button>
      </div>
    </div>
  );
}

/* ── Alert detail row ──────────────────────────────────────────── */

function AlertDetailPanel({ alert }: { alert: LifecycleAlert }) {
  const details = alert.details || {};
  const prevKw = (details.previous_keywords as string[]) || [];
  const currKw = (details.current_keywords as string[]) || [];
  const newKw = (details.new_keywords as string[]) || [];
  const modelInfo = details.model_info as Record<string, unknown> | undefined;
  const previousHash = details.previous_hash as string | undefined;
  const newHash = details.new_hash as string | undefined;

  return (
    <div className="space-y-3 border-t border-(--line) bg-(--paper) px-6 py-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {/* Alert type */}
        <div>
          <p className={MICRO_LABEL}>Alert type</p>
          <p className="mt-0.5 text-sm text-(--t-1)">{alertTypeLabel(alert.alert_type)}</p>
        </div>

        {/* Source URL */}
        {alert.source_url && (
          <div>
            <p className={MICRO_LABEL}>Source page</p>
            <a
              href={alert.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-0.5 inline-flex items-center gap-1 text-sm text-(--purple) hover:underline"
            >
              <span className="max-w-[300px] truncate">{alert.source_url}</span>
              <ExternalLink size={12} />
            </a>
          </div>
        )}

        {/* Acknowledged by */}
        {alert.acknowledged_by_email && (
          <div>
            <p className={MICRO_LABEL}>Acknowledged by</p>
            <p className="mt-0.5 text-sm text-(--t-1)">
              {alert.acknowledged_by_email}
              {alert.acknowledged_at && (
                <span className="ml-2 text-xs text-(--t-3)">
                  (<ClientSafeDate date={alert.acknowledged_at} format="datetime" />)
                </span>
              )}
            </p>
          </div>
        )}

        {/* Resolved at */}
        {alert.resolved_at && (
          <div>
            <p className={MICRO_LABEL}>Resolved at</p>
            <p className="mt-0.5 text-sm text-(--t-1)">
              <ClientSafeDate date={alert.resolved_at} format="datetime" />
            </p>
          </div>
        )}
      </div>

      {/* Full description */}
      {alert.description && (
        <div>
          <p className={MICRO_LABEL}>Description</p>
          <p className="mt-0.5 text-sm leading-relaxed text-(--t-2)">{alert.description}</p>
        </div>
      )}

      {/* Lifecycle keyword diff */}
      {(prevKw.length > 0 || currKw.length > 0) && (
        <div>
          <p className={MICRO_LABEL}>Lifecycle keyword changes</p>
          <div className="mt-1 flex flex-wrap gap-2">
            {newKw.length > 0 && (
              <div className="flex items-center gap-1">
                <span className="text-xs font-medium text-(--good)">New:</span>
                {newKw.map((kw) => (
                  <Chip key={kw} color="success">
                    {kw}
                  </Chip>
                ))}
              </div>
            )}
            {prevKw.length > 0 && (
              <div className="flex items-center gap-1">
                <span className="text-xs font-medium text-(--t-3)">Previous:</span>
                {prevKw.map((kw) => (
                  <Chip key={kw}>{kw}</Chip>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Model info from new model alerts */}
      {modelInfo && (
        <div>
          <p className={MICRO_LABEL}>Detected model info</p>
          <div className="mt-1 flex flex-wrap gap-2">
            {modelInfo.is_ours && <Chip color="danger">Used by our platform</Chip>}
            {(modelInfo.lifecycle_keywords as string[] | undefined)?.map((kw) => (
              <Chip key={String(kw)} color="warning">
                {String(kw)}
              </Chip>
            ))}
            {(modelInfo.dates as string[] | undefined)?.map((d) => (
              <Chip key={String(d)} color="info">
                {String(d)}
              </Chip>
            ))}
          </div>
        </div>
      )}

      {/* Content hash diff (page_changed alerts) */}
      {previousHash && newHash && (
        <div>
          <p className={MICRO_LABEL}>Content hash change</p>
          <div className="mt-1 flex items-center gap-2 font-(family-name:--mono) text-xs text-(--t-3)">
            <span>{previousHash.substring(0, 16)}...</span>
            <span className="text-(--purple)">-&gt;</span>
            <span>{newHash.substring(0, 16)}...</span>
          </div>
        </div>
      )}

      {/* Ack notes */}
      {details.ack_notes && (
        <div>
          <p className={MICRO_LABEL}>Acknowledgment notes</p>
          <p className="mt-0.5 text-sm italic text-(--t-2)">{String(details.ack_notes)}</p>
        </div>
      )}
    </div>
  );
}

/* ── Alerts Tab ─────────────────────────────────────────────────── */

function AlertsTab({
  alerts,
  actionInFlight,
  onAcknowledge,
  onResolve,
  page,
  pageSize,
  total,
  onPageChange,
  filterStatus,
  filterProvider,
  filterSeverity,
  onFilterStatus,
  onFilterProvider,
  onFilterSeverity,
}: {
  alerts: LifecycleAlert[];
  actionInFlight: number | null;
  onAcknowledge: (id: number) => void;
  onResolve: (id: number) => void;
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (p: number) => void;
  filterStatus: string;
  filterProvider: string;
  filterSeverity: string;
  onFilterStatus: (v: string) => void;
  onFilterProvider: (v: string) => void;
  onFilterSeverity: (v: string) => void;
}) {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const hasFilters = filterStatus || filterProvider || filterSeverity;

  return (
    <div className="space-y-3">
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-2">
        <Filter size={14} className="text-(--t-3)" />
        <FilterSelect
          label="Status"
          value={filterStatus}
          options={[
            { value: "active", label: "Active" },
            { value: "acknowledged", label: "Acknowledged" },
            { value: "resolved", label: "Resolved" },
          ]}
          onChange={onFilterStatus}
        />
        <FilterSelect
          label="Provider"
          value={filterProvider}
          options={Object.entries(PROVIDER_LABELS).map(([v, l]) => ({ value: v, label: l }))}
          onChange={onFilterProvider}
        />
        <FilterSelect
          label="Severity"
          value={filterSeverity}
          options={[
            { value: "critical", label: "Critical" },
            { value: "warning", label: "Warning" },
            { value: "info", label: "Info" },
          ]}
          onChange={onFilterSeverity}
        />
        {hasFilters && (
          <button
            type="button"
            onClick={() => {
              onFilterStatus("");
              onFilterProvider("");
              onFilterSeverity("");
            }}
            className="flex items-center gap-1 text-xs text-(--purple) hover:underline"
          >
            <X size={12} />
            Clear filters
          </button>
        )}
        <span className={`${MONO_META} ml-auto`}>
          {total} alert{total !== 1 ? "s" : ""}
        </span>
      </div>

      {alerts.length === 0 ? (
        <div className={`${WSEC} flex flex-col items-center gap-4 py-16 text-center`}>
          <CheckCircle size={40} className="text-(--good)" />
          <div>
            <p className="font-(family-name:--disp) text-base font-bold text-(--t-1)">
              {hasFilters ? "No matching alerts" : "No lifecycle alerts"}
            </p>
            <p className="mt-1 text-xs text-(--t-3)">
              {hasFilters
                ? "Try adjusting your filters to see more results."
                : "All monitored AI providers are operating normally. Run a check to scan for updates."}
            </p>
          </div>
        </div>
      ) : (
        <div className={TABLE_SECTION}>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-(--line)">
                  <th className={`${TH} w-8`} />
                  <th className={TH}>Severity</th>
                  <th className={TH}>Provider</th>
                  <th className={TH}>Title</th>
                  <th className={TH}>Affected models</th>
                  <th className={TH}>Status</th>
                  <th className={TH}>Created at</th>
                  <th className={`${TH} text-right`}>Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-(--line)">
                {alerts.map((alert) => {
                  const isExpanded = expandedId === alert.id;
                  const models = alert.affected_models || [];
                  return (
                    <React.Fragment key={alert.id}>
                      <tr
                        className={cx(
                          "cursor-pointer transition-colors hover:bg-(--paper)",
                          isExpanded && "bg-(--paper)"
                        )}
                        onClick={() => setExpandedId(isExpanded ? null : alert.id)}
                      >
                        <td className={TD}>
                          {isExpanded ? (
                            <ChevronUp size={14} className="text-(--t-3)" />
                          ) : (
                            <ChevronDown size={14} className="text-(--t-3)" />
                          )}
                        </td>
                        <td className={TD}>
                          <Chip color={severityChipColor(alert.severity)}>
                            {severityIcon(alert.severity)}
                            {alert.severity}
                          </Chip>
                        </td>
                        <td className={cx(TD, "font-semibold text-(--t-1)")}>
                          {providerLabel(alert.provider)}
                        </td>
                        <td className={TD}>
                          <div>
                            <p className="text-sm font-medium text-(--t-1)">
                              {alert.title.replace(/^\[OUR MODEL\]\s*/, "")}
                              {alert.title.startsWith("[OUR MODEL]") && (
                                <span className="ml-2 align-middle">
                                  <Chip color="danger">OUR MODEL</Chip>
                                </span>
                              )}
                            </p>
                            <p className="mt-0.5 text-[11px] text-(--t-3)">
                              {alertTypeLabel(alert.alert_type)}
                            </p>
                          </div>
                        </td>
                        <td className={TD}>
                          <div className="flex max-w-[200px] flex-wrap gap-1">
                            {models.slice(0, 3).map((model) => (
                              <Chip key={model}>{model}</Chip>
                            ))}
                            {models.length > 3 && <Chip>+{models.length - 3}</Chip>}
                            {models.length === 0 && <span className="text-(--t-3)">-</span>}
                          </div>
                        </td>
                        <td className={TD}>
                          <Chip color={statusChipColor(alert.status)}>{alert.status}</Chip>
                        </td>
                        <td className={cx(TD, "whitespace-nowrap")}>
                          <span className="text-[11px] text-(--t-3)">
                            <ClientSafeDate date={alert.created_at} format="datetime" />
                          </span>
                        </td>
                        <td className={cx(TD, "text-right")} onClick={(e) => e.stopPropagation()}>
                          <div className="flex items-center justify-end gap-2">
                            {alert.status === "active" && (
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={actionInFlight === alert.id}
                                loading={actionInFlight === alert.id}
                                onClick={() => onAcknowledge(alert.id)}
                              >
                                <Eye size={14} />
                                Ack
                              </Button>
                            )}
                            {(alert.status === "active" || alert.status === "acknowledged") && (
                              <Button
                                variant="outline"
                                size="sm"
                                disabled={actionInFlight === alert.id}
                                loading={actionInFlight === alert.id}
                                onClick={() => onResolve(alert.id)}
                              >
                                <Check size={14} />
                                Resolve
                              </Button>
                            )}
                            {alert.status === "resolved" && (
                              <span className="text-xs italic text-(--t-3)">Resolved</span>
                            )}
                          </div>
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr key={`detail-${alert.id}`}>
                          <td colSpan={8} className="p-0">
                            <AlertDetailPanel alert={alert} />
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          <PaginationBar
            page={page}
            pageSize={pageSize}
            total={total}
            onPageChange={onPageChange}
          />
        </div>
      )}
    </div>
  );
}

/* ── Snapshots Tab ──────────────────────────────────────────────── */

function SnapshotsTab({
  snapshots,
  page,
  pageSize,
  total,
  onPageChange,
  filterProvider,
  onFilterProvider,
}: {
  snapshots: LifecycleSnapshot[];
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (p: number) => void;
  filterProvider: string;
  onFilterProvider: (v: string) => void;
}) {
  return (
    <div className="space-y-3">
      {/* Filter bar */}
      <div className="flex items-center gap-2">
        <Filter size={14} className="text-(--t-3)" />
        <FilterSelect
          label="Provider"
          value={filterProvider}
          options={Object.entries(PROVIDER_LABELS).map(([v, l]) => ({ value: v, label: l }))}
          onChange={onFilterProvider}
        />
        {filterProvider && (
          <button
            type="button"
            onClick={() => onFilterProvider("")}
            className="flex items-center gap-1 text-xs text-(--purple) hover:underline"
          >
            <X size={12} />
            Clear
          </button>
        )}
        <span className={`${MONO_META} ml-auto`}>
          {total} snapshot{total !== 1 ? "s" : ""}
        </span>
      </div>

      {snapshots.length === 0 ? (
        <div className={`${WSEC} flex flex-col items-center gap-4 py-16 text-center`}>
          <Clock size={40} className="text-(--t-3)" />
          <div>
            <p className="font-(family-name:--disp) text-base font-bold text-(--t-1)">
              No snapshots yet
            </p>
            <p className="mt-1 text-xs text-(--t-3)">
              Snapshots will appear after the first lifecycle check runs.
            </p>
          </div>
        </div>
      ) : (
        <div className={TABLE_SECTION}>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-(--line)">
                  <th className={TH}>Provider</th>
                  <th className={TH}>Source URL</th>
                  <th className={TH}>Page type</th>
                  <th className={TH}>Content hash</th>
                  <th className={TH}>Models found</th>
                  <th className={TH}>Fetched at</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-(--line)">
                {snapshots.map((snap) => (
                  <tr key={snap.id} className="transition-colors hover:bg-(--paper)">
                    <td className={cx(TD, "font-semibold text-(--t-1)")}>
                      {providerLabel(snap.provider)}
                    </td>
                    <td className={TD}>
                      <a
                        href={snap.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-sm text-(--purple) hover:underline"
                      >
                        <span className="max-w-[200px] truncate">{snap.source_url}</span>
                        <ExternalLink size={12} />
                      </a>
                    </td>
                    <td className={TD}>
                      <Chip color={snap.page_type === "deprecations" ? "warning" : "info"}>
                        {snap.page_type}
                      </Chip>
                    </td>
                    <td className={cx(TD, "font-(family-name:--mono) text-xs text-(--t-3)")}>
                      {snap.content_hash.substring(0, 12)}
                    </td>
                    <td className={TD}>
                      <Chip color="info">{snap.extracted_models?.length ?? 0}</Chip>
                    </td>
                    <td className={cx(TD, "whitespace-nowrap")}>
                      <span className="text-[11px] text-(--t-3)">
                        <ClientSafeDate date={snap.fetched_at} format="datetime" />
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <PaginationBar
            page={page}
            pageSize={pageSize}
            total={total}
            onPageChange={onPageChange}
          />
        </div>
      )}
    </div>
  );
}

/* ── Sources Tab ────────────────────────────────────────────────── */

function SourcesTab({ sources }: { sources: LifecycleSource[] }) {
  if (sources.length === 0) {
    return (
      <div className={`${WSEC} flex flex-col items-center gap-4 py-16 text-center`}>
        <ExternalLink size={40} className="text-(--t-3)" />
        <div>
          <p className="font-(family-name:--disp) text-base font-bold text-(--t-1)">
            No sources configured
          </p>
          <p className="mt-1 text-xs text-(--t-3)">
            Configure model lifecycle monitoring sources to begin tracking provider changes.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className={TABLE_SECTION}>
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-(--line)">
              <th className={TH}>Provider</th>
              <th className={TH}>URL</th>
              <th className={TH}>Page type</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-(--line)">
            {sources.map((source, idx) => (
              <tr
                key={`${source.provider}-${source.page_type}-${idx}`}
                className="transition-colors hover:bg-(--paper)"
              >
                <td className={cx(TD, "font-semibold text-(--t-1)")}>
                  {providerLabel(source.provider)}
                </td>
                <td className={TD}>
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-sm text-(--purple) hover:underline"
                  >
                    <span className="max-w-[300px] truncate">{source.url}</span>
                    <ExternalLink size={12} />
                  </a>
                </td>
                <td className={TD}>
                  <Chip color={source.page_type === "deprecations" ? "warning" : "info"}>
                    {source.page_type}
                  </Chip>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
