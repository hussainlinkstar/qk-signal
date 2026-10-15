"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  HardDrive,
  ListChecks,
  Loader2,
  Mail,
  RefreshCcw,
  Server,
  Trash2,
  XCircle,
  Zap,
} from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import { ClientSafeDate } from "@/lib/dateFormat";
import Button from "@/components/ui/Button";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import SignalDataTable, { type SignalDataTableColumn } from "@/components/signal/SignalDataTable";
import ToggleSwitch from "@/components/ui/ToggleSwitch";
import { NativeSelect } from "@/components/ui/native-select";

/* -------------------------------------------------------------------------- */
/*  Types                                                                      */
/* -------------------------------------------------------------------------- */

type QueueInfo = {
  name: string;
  key: string;
  depth: number;
  worker_name: string;
  worker_alive: boolean;
  worker_last_seen: string | null;
  worker_pid: number | null;
  jobs_processed: number;
};

type JobQueueOverview = {
  queues: QueueInfo[];
  email_outbox_pending: number;
  audit_metrics: {
    jobs_started: number;
    jobs_succeeded: number;
    jobs_failed: number;
    job_retries: number;
    job_duration_seconds_total: number;
  } | null;
};

type JobEntry = {
  id: string;
  queue: string;
  user_id: number;
  user_email: string | null;
  status: string;
  url: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  last_heartbeat: string | null;
};

type RecentJobsPage = {
  items: JobEntry[];
  total: number;
  page: number;
  page_size: number;
};

type JobStats = {
  jobs_by_status: Record<string, number>;
  audit_jobs_24h: number;
  audit_jobs_7d: number;
  pdf_jobs_24h: number;
  pdf_jobs_7d: number;
  avg_duration_seconds: number | null;
  failure_rate_pct: number;
};

/* -------------------------------------------------------------------------- */
/*  Constants                                                                  */
/* -------------------------------------------------------------------------- */

const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const MONO_META = MICRO_LABEL.replace("uppercase ", "");
const WSEC = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";
const WSTAT = "rounded-[22px] border-0 bg-white px-4 py-3";
const CHIP =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";
const PAGER_BTN =
  "inline-flex h-8 min-w-8 items-center justify-center rounded-(--r-sm) px-2 text-(--t-2) hover:bg-(--line-2) hover:text-(--t-1) disabled:opacity-40";

const STATUS_CONFIG: Record<string, { chip: string; icon: React.ReactNode }> = {
  queued: { chip: `${CHIP} text-(--purple) bg-(--purple-s)`, icon: <Clock size={10} /> },
  running: {
    chip: `${CHIP} text-(--warn) bg-(--warn-s)`,
    icon: <Loader2 size={10} className="animate-spin" />,
  },
  succeeded: {
    chip: `${CHIP} text-(--good) bg-(--good-s)`,
    icon: <CheckCircle2 size={10} />,
  },
  failed: { chip: `${CHIP} text-(--bad) bg-(--bad-s)`, icon: <XCircle size={10} /> },
};

const QUEUE_ICONS: Record<string, React.ReactNode> = {
  audit_jobs: <Zap size={16} className="text-(--purple)" />,
  pdf_jobs: <HardDrive size={16} className="text-(--purple)" />,
  "billing:webhook_events": <Activity size={16} className="text-(--good)" />,
  visibility_index_jobs: <Server size={16} className="text-(--warn)" />,
};

/* -------------------------------------------------------------------------- */
/*  Component                                                                  */
/* -------------------------------------------------------------------------- */

export default function AdminJobsPage() {
  useAdminAccess();
  const { getToken } = useAuth();

  const [queues, setQueues] = useState<JobQueueOverview | null>(null);
  const [jobs, setJobs] = useState<RecentJobsPage | null>(null);
  const [stats, setStats] = useState<JobStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [queueFilter, setQueueFilter] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [purging, setPurging] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const headers = useCallback(async () => {
    const token = await getToken();
    return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
  }, [getToken]);

  /* ---- Fetch helpers ---- */

  const fetchQueues = useCallback(async () => {
    try {
      const h = await headers();
      const res = await fetch("/api/admin/jobs/queues", { headers: h });
      if (res.ok) setQueues(await res.json());
    } catch {
      /* ignore */
    }
  }, [headers]);

  const fetchJobs = useCallback(async () => {
    try {
      const h = await headers();
      const params = new URLSearchParams({ page: String(page), page_size: "25" });
      if (queueFilter) params.set("queue", queueFilter);
      if (statusFilter) params.set("status", statusFilter);
      const res = await fetch(`/api/admin/jobs/recent?${params}`, { headers: h });
      if (res.ok) setJobs(await res.json());
    } catch {
      /* ignore */
    }
  }, [headers, page, queueFilter, statusFilter]);

  const fetchStats = useCallback(async () => {
    try {
      const h = await headers();
      const res = await fetch("/api/admin/jobs/stats", { headers: h });
      if (res.ok) setStats(await res.json());
    } catch {
      /* ignore */
    }
  }, [headers]);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    await Promise.all([fetchQueues(), fetchJobs(), fetchStats()]);
    setLoading(false);
  }, [fetchQueues, fetchJobs, fetchStats]);

  /* ---- Effects ---- */

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(fetchQueues, 10_000);
    return () => clearInterval(id);
  }, [autoRefresh, fetchQueues]);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  /* ---- Purge handler ---- */

  const handlePurge = useCallback(
    async (queueKey: string) => {
      if (!confirm(`Clear all pending jobs from ${queueKey}? This action cannot be reversed.`))
        return;
      setPurging(queueKey);
      try {
        const h = await headers();
        await fetch(`/api/admin/jobs/${encodeURIComponent(queueKey)}/purge`, {
          method: "POST",
          headers: h,
        });
        await fetchAll();
      } finally {
        setPurging(null);
      }
    },
    [headers, fetchAll]
  );

  /* ---- Derived ---- */

  const totalPages = useMemo(() => (jobs ? Math.ceil(jobs.total / jobs.page_size) : 1), [jobs]);

  const depthColor = (depth: number) => {
    if (depth < 0) return "text-(--t-3)";
    if (depth <= 5) return "text-(--good)";
    if (depth <= 20) return "text-(--warn)";
    return "text-(--bad)";
  };

  const jobColumns: SignalDataTableColumn<JobEntry>[] = [
    {
      key: "id",
      header: "Job ID",
      renderCell: (job) => (
        <span className="font-(family-name:--mono) text-xs text-(--t-2)">
          {job.id.slice(0, 8)}…
        </span>
      ),
    },
    {
      key: "queue",
      header: "Queue",
      renderCell: (job) => <span className="text-(--t-2)">{job.queue}</span>,
    },
    {
      key: "status",
      header: "Status",
      renderCell: (job) => {
        const cfg = STATUS_CONFIG[job.status] || STATUS_CONFIG.queued;
        return (
          <span className={cfg.chip}>
            {cfg.icon}
            {job.status}
          </span>
        );
      },
    },
    {
      key: "user",
      header: "User",
      renderCell: (job) => (
        <span className="text-(--t-2)">{job.user_email || `#${job.user_id}`}</span>
      ),
    },
    {
      key: "url",
      header: "URL",
      renderCell: (job) => (
        <span className="block max-w-[200px] truncate text-(--t-2)">{job.url || "-"}</span>
      ),
    },
    {
      key: "created",
      header: "Created",
      renderCell: (job) => (
        <span className="text-(--t-2)">
          <ClientSafeDate date={job.created_at} format="datetime" />
        </span>
      ),
    },
    {
      key: "duration",
      header: "Duration",
      renderCell: (job) => {
        const duration =
          job.started_at && job.completed_at
            ? `${((new Date(job.completed_at).getTime() - new Date(job.started_at).getTime()) / 1000).toFixed(1)}s`
            : job.started_at
              ? "running..."
              : "-";
        return <span className="font-(family-name:--mono) text-xs text-(--t-2)">{duration}</span>;
      },
    },
    {
      key: "error",
      header: "Error",
      renderCell: (job) =>
        job.error ? (
          <span className="block max-w-[200px] truncate text-(--bad)" title={job.error}>
            <AlertTriangle size={10} className="mr-1 inline" />
            {job.error.slice(0, 80)}
          </span>
        ) : (
          <span className="text-(--t-3)">-</span>
        ),
    },
  ];

  /* ---- Render ---- */

  const { setHeader } = useWorkspacePageHeader();
  useEffect(() => {
    setHeader({
      actions: (
        <>
          <label className="flex items-center gap-2">
            <ToggleSwitch
              checked={autoRefresh}
              onChange={setAutoRefresh}
              aria-label="Auto-refresh"
            />
            <span className={`${MICRO_LABEL} max-sm:hidden`}>Auto-refresh (10s)</span>
          </label>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void fetchAll()}
            disabled={loading}
            aria-label="Refresh"
            title="Refresh"
            className="h-8 w-8 p-0"
          >
            <RefreshCcw size={14} className={loading ? "animate-spin" : ""} />
          </Button>
        </>
      ),
    });
    return () => setHeader(null);
  }, [autoRefresh, fetchAll, loading, setHeader]);

  return (
    <>
      <DashboardPageIntro icon={ListChecks} title="Job queue">
        Monitor background tasks, worker status, and execution history.
      </DashboardPageIntro>

      {/* Queue status cards */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        {queues?.queues.map((q) => (
          <div key={q.key} className={WSEC}>
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                {QUEUE_ICONS[q.key] || <Server size={16} className="text-(--t-2)" />}
                <span className="text-sm font-semibold text-(--t-1)">{q.name}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span
                  className={`h-2.5 w-2.5 rounded-full ${
                    q.worker_alive ? "animate-pulse bg-(--good)" : "bg-(--bad)"
                  }`}
                />
                <span className={MICRO_LABEL}>{q.worker_alive ? "active" : "offline"}</span>
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span className="text-(--t-3)">Queue depth</span>
                <span className={`font-(family-name:--mono) font-semibold ${depthColor(q.depth)}`}>
                  {q.depth < 0 ? "N/A" : q.depth}
                </span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-(--t-3)">Jobs processed</span>
                <span className="font-(family-name:--mono) text-(--t-2)">{q.jobs_processed}</span>
              </div>
              {q.worker_pid && (
                <div className="flex justify-between text-xs">
                  <span className="text-(--t-3)">PID</span>
                  <span className="font-(family-name:--mono) text-(--t-2)">{q.worker_pid}</span>
                </div>
              )}
              {q.worker_last_seen && (
                <div className="flex justify-between text-xs">
                  <span className="text-(--t-3)">Last seen</span>
                  <span className="text-(--t-2)">
                    <ClientSafeDate date={q.worker_last_seen} format="datetime" />
                  </span>
                </div>
              )}
            </div>

            {q.depth > 0 && (
              <button
                onClick={() => handlePurge(q.key)}
                disabled={purging === q.key}
                className="mt-3 flex items-center gap-1 font-(family-name:--mono) text-[10.5px] tracking-[0.04em] text-(--bad) transition-colors hover:text-(--t-1) disabled:opacity-40"
              >
                <Trash2 size={10} />
                {purging === q.key ? "Clearing..." : "Clear queue"}
              </button>
            )}
          </div>
        ))}

        {/* Email outbox pseudo-queue */}
        {queues && (
          <div className={WSEC}>
            <div className="mb-3 flex items-center gap-2">
              <Mail size={16} className="text-(--bad)" />
              <span className="text-sm font-semibold text-(--t-1)">Email Outbox</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-(--t-3)">Pending emails</span>
              <span
                className={`font-(family-name:--mono) font-semibold ${depthColor(queues.email_outbox_pending)}`}
              >
                {queues.email_outbox_pending}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Stats row */}
      {stats && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
          {[
            { label: "Audits (24h)", value: stats.audit_jobs_24h },
            { label: "Audits (7d)", value: stats.audit_jobs_7d },
            { label: "PDF jobs (24h)", value: stats.pdf_jobs_24h },
            { label: "PDF jobs (7d)", value: stats.pdf_jobs_7d },
            {
              label: "Avg duration",
              value: stats.avg_duration_seconds != null ? `${stats.avg_duration_seconds}s` : "-",
            },
            {
              label: "Failure rate",
              value: `${stats.failure_rate_pct}%`,
              warn: stats.failure_rate_pct > 10,
            },
          ].map((s) => (
            <div key={s.label} className={`${WSTAT} text-center`}>
              <p className={`${MICRO_LABEL} mb-1`}>{s.label}</p>
              <p
                className={`font-(family-name:--mono) text-lg font-semibold ${
                  "warn" in s && s.warn ? "text-(--bad)" : "text-(--t-1)"
                }`}
              >
                {s.value}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Audit metrics from Redis */}
      {queues?.audit_metrics && (
        <div className={WSEC}>
          <h3 className="m-0 mb-3 flex items-center gap-2 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)">
            <Activity size={16} className="text-(--purple)" />
            Worker performance metrics
          </h3>
          <div className="grid grid-cols-3 gap-4 text-center md:grid-cols-6">
            {Object.entries(queues.audit_metrics).map(([k, v]) => (
              <div key={k}>
                <p className={MONO_META}>{k.replace(/_/g, " ")}</p>
                <p className="font-(family-name:--mono) text-sm text-(--t-1)">
                  {typeof v === "number" ? v.toLocaleString() : v}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent jobs table */}
      <SignalDataTable
        columns={jobColumns}
        rows={jobs?.items ?? []}
        rowKey={(job) => `${job.queue}-${job.id}`}
        emptyLabel="No jobs found matching the current filters."
        metaLabel={jobs ? `${jobs.total} total` : undefined}
        pageSize={25}
        tools={
          <>
            <NativeSelect
              variant="auth"
              value={queueFilter}
              onChange={(e) => {
                setQueueFilter(e.target.value);
                setPage(1);
              }}
              className="h-8 w-auto text-[12.5px]"
              aria-label="Queue filter"
            >
              <option value="">All queues</option>
              <option value="audit_jobs">Audit jobs</option>
              <option value="pdf_jobs">PDF jobs</option>
            </NativeSelect>
            <NativeSelect
              variant="auth"
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value);
                setPage(1);
              }}
              className="h-8 w-auto text-[12.5px]"
              aria-label="Status filter"
            >
              <option value="">All statuses</option>
              <option value="queued">Queued</option>
              <option value="running">Running</option>
              <option value="succeeded">Succeeded</option>
              <option value="failed">Failed</option>
            </NativeSelect>
          </>
        }
        footer={
          <>
            <span className="font-(family-name:--mono) text-[11px] text-(--t-3)">
              Page {jobs?.page ?? 1} of {totalPages}
            </span>
            <nav className="ms-auto inline-flex items-center gap-1" aria-label="Pagination">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                aria-label="Previous page"
                className={PAGER_BTN}
              >
                <ChevronLeft size={14} />
              </button>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                aria-label="Next page"
                className={PAGER_BTN}
              >
                <ChevronRight size={14} />
              </button>
            </nav>
          </>
        }
      />
    </>
  );
}
