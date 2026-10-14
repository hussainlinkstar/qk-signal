"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Monitor,
  Database,
  HardDrive,
  Wifi,
  RefreshCw,
  Activity,
  Clock,
  Layers,
  AlertTriangle,
  CheckCircle,
  XCircle,
} from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import BrandLogo from "@/components/ui/BrandLogo";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { AdminInlineError } from "@/components/admin/AdminInlineError";
import { AdminCardSkeleton } from "@/components/admin/AdminTableSkeleton";
import {
  CHART_AXIS_TICK_SMALL,
  CHART_GRID_STROKE,
  CHART_TOOLTIP_STYLE,
} from "@/components/ui/chartTokens";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

/* ── Types ──────────────────────────────────────────────────────── */

type InfraMetrics = {
  timestamp: string;
  process: {
    memory_rss_mb: number | null;
    memory_vms_mb: number | null;
    uptime_seconds: number | null;
    threads: number | null;
    load_avg_1m?: number;
    load_avg_5m?: number;
    load_avg_15m?: number;
  };
  database: {
    pool_size?: number;
    checked_in?: number;
    checked_out?: number;
    overflow?: number;
    max_overflow?: number;
    db_size_mb?: number | null;
    active_connections?: number;
    total_connections?: number;
    top_tables?: { table: string; rows: number; size_mb: number }[];
  };
  redis: {
    used_memory_mb?: number;
    used_memory_peak_mb?: number;
    connected_clients?: number;
    total_keys?: number;
    queue_depths?: Record<string, number>;
    workers?: {
      name: string;
      status: string;
      last_seen: string | null;
      pid?: number;
      jobs_processed?: number;
      last_error?: string | null;
      age_seconds?: number;
    }[];
  };
  request_stats: {
    total_requests: number;
    by_status: Record<string, number>;
    error_rate_percent: number;
  };
};

/* ── Design tokens ──────────────────────────────────────────────── */

const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const MONO_META = MICRO_LABEL.replace("uppercase ", "");
const WSEC = "rounded-(--r) border border-(--line) bg-(--panel) px-[22px] py-[18px]";
const SEC_TITLE =
  "m-0 mb-4 flex items-center gap-2 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)";
const INSET = "rounded-(--r-md) border border-(--line) bg-(--paper) p-3";
const CHIP =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";

/* ── Color helpers ──────────────────────────────────────────────── */

function getGaugeColor(value: number, warning: number, critical: number) {
  if (value >= critical) return "text-(--bad)";
  if (value >= warning) return "text-(--warn)";
  return "text-(--good)";
}

function formatUptime(seconds: number | null): string {
  if (!seconds) return "-";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

/* ── Gauge ring ─────────────────────────────────────────────────── */

function GaugeRing({
  label,
  value,
  max,
  unit,
  warning,
  critical,
}: {
  label: string;
  value: number | null;
  max: number;
  unit: string;
  warning: number;
  critical: number;
}) {
  const pct = value != null ? Math.min((value / max) * 100, 100) : 0;
  const ring = getGaugeColor(pct, warning, critical);
  const circumference = 2 * Math.PI * 36;
  const offset = circumference - (pct / 100) * circumference;

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative h-24 w-24">
        <svg className="h-24 w-24 -rotate-90" viewBox="0 0 80 80">
          <circle
            cx="40"
            cy="40"
            r="36"
            fill="none"
            strokeWidth="6"
            className="stroke-(--line-2)"
          />
          <circle
            cx="40"
            cy="40"
            r="36"
            fill="none"
            strokeWidth="6"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
            className={`${ring} transition-all duration-700`}
            style={{ stroke: "currentColor" }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="font-(family-name:--disp) text-lg font-bold text-(--t-1)">
            {value != null ? Math.round(value) : "-"}
          </span>
          <span className={`${MICRO_LABEL} text-[9px]`}>{unit}</span>
        </div>
      </div>
      <span className={MICRO_LABEL}>{label}</span>
    </div>
  );
}

/* ── Stat tile ──────────────────────────────────────────────────── */

function StatTile({
  label,
  value,
  icon,
  color = "text-(--purple)",
}: {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  color?: string;
}) {
  return (
    <div className={`${INSET} flex items-center gap-3`}>
      <div
        className={`flex h-9 w-9 items-center justify-center rounded-(--r-sm) bg-(--panel) ${color}`}
      >
        {icon}
      </div>
      <div>
        <p className={MICRO_LABEL}>{label}</p>
        <p className="text-sm font-semibold text-(--t-1)">{value}</p>
      </div>
    </div>
  );
}

/* ── Queue depth colors ──────────────────────────────────────────── */

function queueColor(depth: number): string {
  if (depth > 200) return "var(--bad)";
  if (depth > 50) return "var(--warn)";
  return "var(--purple)";
}

/* ── Chart tooltip ──────────────────────────────────────────────── */

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { name: string; value: number; color?: string }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div style={CHART_TOOLTIP_STYLE} className="px-3 py-2">
      <p className={`${MICRO_LABEL} mb-1`}>{label}</p>
      {payload.map((e, i) => (
        <p key={i} className="text-xs font-semibold" style={{ color: e.color }}>
          {e.name}: {e.value}
        </p>
      ))}
    </div>
  );
}

/* ── Main page ──────────────────────────────────────────────────── */

const REFRESH_OPTIONS = [
  { label: "5s", value: 5000 },
  { label: "15s", value: 15000 },
  { label: "30s", value: 30000 },
  { label: "60s", value: 60000 },
  { label: "Off", value: 0 },
];

export default function AdminInfrastructurePage() {
  const { getToken, isSignedIn } = useAuth();
  const { isLoading: isGuardLoading } = useAdminAccess();
  const { setHeader } = useWorkspacePageHeader();

  const [metrics, setMetrics] = useState<InfraMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshInterval, setRefreshInterval] = useState(15000);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) throw new Error("Not authenticated.");
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const loadMetrics = useCallback(async () => {
    if (!isSignedIn) return;
    try {
      const headers = await getAuthHeaders();
      const res = await fetch("/api/admin/infrastructure/metrics", { headers });
      if (!res.ok) throw new Error("Failed to load infrastructure metrics.");
      const data = await res.json();
      setMetrics(data);
      setError("");
      setLastUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load metrics.");
    } finally {
      setLoading(false);
    }
  }, [getAuthHeaders, isSignedIn]);

  useEffect(() => {
    loadMetrics();
  }, [loadMetrics]);

  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    if (refreshInterval > 0) {
      intervalRef.current = setInterval(loadMetrics, refreshInterval);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [refreshInterval, loadMetrics]);

  /* Page-scoped `.top` actions: polling interval segmented control
     (hidden under sm, where it stays reachable inside the page body)
     and an icon-only manual refresh. */
  useEffect(() => {
    setHeader({
      actions: (
        <>
          <div
            role="group"
            aria-label="Auto-refresh interval"
            className="hidden items-center gap-0.5 rounded-(--r-md) border border-(--line) bg-(--paper) p-0.5 sm:flex"
          >
            {REFRESH_OPTIONS.map((opt) => (
              <button
                key={opt.label}
                type="button"
                onClick={() => setRefreshInterval(opt.value)}
                className={`rounded-(--r-sm) px-2.5 py-1 font-(family-name:--mono) text-[11px] tracking-[0.04em] transition-colors ${
                  refreshInterval === opt.value
                    ? "bg-(--panel) text-(--t-1) shadow-sm"
                    : "text-(--t-3) hover:text-(--t-1)"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={loadMetrics}
            aria-label="Refresh now"
            title="Refresh now"
            className="inline-flex h-8 w-8 items-center justify-center rounded-(--r-sm) border border-(--line) bg-(--panel) text-(--t-2) transition-colors hover:text-(--t-1) focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple)"
          >
            <RefreshCw size={14} />
          </button>
        </>
      ),
    });
    return () => setHeader(null);
  }, [loadMetrics, refreshInterval, setHeader]);

  if (loading || isGuardLoading) {
    return (
      <>
        <DashboardPageIntro icon={Monitor} title="System infrastructure" />
        <AdminCardSkeleton cards={4} />
      </>
    );
  }

  if (error && !metrics) {
    return <AdminInlineError message={error} onRetry={loadMetrics} />;
  }

  const proc = metrics?.process;
  const db = metrics?.database;
  const red = metrics?.redis;
  const req = metrics?.request_stats;
  const workers = red?.workers || [];
  const queueData = Object.entries(red?.queue_depths || {}).map(([name, depth]) => ({
    name: name.replace(/_/g, " ").replace("billing:", "billing "),
    depth,
  }));
  const poolMax = (db?.pool_size || 5) + (db?.max_overflow || 10);
  const poolUsedPct = poolMax > 0 ? ((db?.checked_out || 0) / poolMax) * 100 : 0;

  const poolBarColor =
    poolUsedPct > 80 ? "bg-(--bad)" : poolUsedPct > 60 ? "bg-(--warn)" : "bg-(--good)";
  const poolTextColor =
    poolUsedPct > 80 ? "text-(--bad)" : poolUsedPct > 60 ? "text-(--warn)" : "text-(--good)";

  return (
    <>
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <DashboardPageIntro icon={Monitor} title="System infrastructure">
          Monitor server vitals, database performance, and background worker health.
        </DashboardPageIntro>

        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className={MONO_META}>Updated {lastUpdated.toLocaleTimeString()}</span>
          )}
          {/* Mobile duplicate of the `.top` interval control (hidden at sm+). */}
          <div
            role="group"
            aria-label="Auto-refresh interval"
            className="flex items-center gap-0.5 rounded-(--r-md) border border-(--line) bg-(--paper) p-0.5 sm:hidden"
          >
            {REFRESH_OPTIONS.map((opt) => (
              <button
                key={opt.label}
                type="button"
                onClick={() => setRefreshInterval(opt.value)}
                className={`rounded-(--r-sm) px-2.5 py-1 font-(family-name:--mono) text-[11px] tracking-[0.04em] transition-colors ${
                  refreshInterval === opt.value
                    ? "bg-(--panel) text-(--t-1) shadow-sm"
                    : "text-(--t-3) hover:text-(--t-1)"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && <AdminInlineError message={error} onRetry={loadMetrics} />}

      {/* Server vitals */}
      <section className={WSEC}>
        <h2 className={SEC_TITLE}>
          <Activity size={14} className="text-(--purple)" /> Server vitals
        </h2>
        <div className="flex flex-wrap items-center justify-around gap-8">
          <GaugeRing
            label="Memory RSS"
            value={proc?.memory_rss_mb ?? null}
            max={Math.max(proc?.memory_vms_mb ?? 1024, proc?.memory_rss_mb ?? 0, 512)}
            unit="MB"
            warning={70}
            critical={85}
          />
          <div className="grid min-w-[300px] flex-1 grid-cols-2 gap-3">
            <StatTile
              label="Uptime"
              value={formatUptime(proc?.uptime_seconds ?? null)}
              icon={<Clock size={16} />}
              color="text-(--good)"
            />
            <StatTile label="Threads" value={proc?.threads ?? "-"} icon={<Layers size={16} />} />
            <StatTile
              label="Load (1m)"
              value={proc?.load_avg_1m?.toFixed(2) ?? "-"}
              icon={<Activity size={16} />}
              color={
                (proc?.load_avg_1m ?? 0) > 4
                  ? "text-(--bad)"
                  : (proc?.load_avg_1m ?? 0) > 2
                    ? "text-(--warn)"
                    : "text-(--good)"
              }
            />
            <StatTile
              label="VMS"
              value={proc?.memory_vms_mb ? `${proc.memory_vms_mb} MB` : "-"}
              icon={<HardDrive size={16} />}
            />
          </div>
        </div>
      </section>

      {/* Database + Redis */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className={WSEC}>
          <h2 className={SEC_TITLE}>
            <BrandLogo
              brand="postgresql"
              decorative
              variant="tile"
              width={16}
              height={16}
              className="h-6 w-6"
              imageClassName="h-4 w-4"
            />
            Database pool
          </h2>
          <div className="space-y-4">
            <div>
              <div className="mb-1.5 flex justify-between">
                <span className="text-[11px] font-semibold text-(--t-2)">
                  Pool usage: {db?.checked_out ?? 0} / {poolMax}
                </span>
                <span
                  className={`font-(family-name:--mono) text-[11px] font-semibold ${poolTextColor}`}
                >
                  {poolUsedPct.toFixed(0)}%
                </span>
              </div>
              <div className="h-2.5 overflow-hidden rounded-full bg-(--line-2)">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${poolBarColor}`}
                  style={{ width: `${Math.min(poolUsedPct, 100)}%` }}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <StatTile
                label="DB size"
                value={db?.db_size_mb ? `${db.db_size_mb} MB` : "-"}
                icon={<HardDrive size={14} />}
              />
              <StatTile
                label="Active conns"
                value={db?.active_connections ?? "-"}
                icon={<Activity size={14} />}
              />
              <StatTile
                label="Total conns"
                value={db?.total_connections ?? "-"}
                icon={<Wifi size={14} />}
              />
              <StatTile label="Overflow" value={db?.overflow ?? 0} icon={<Layers size={14} />} />
            </div>
          </div>
        </section>

        <section className={WSEC}>
          <h2 className={SEC_TITLE}>
            <BrandLogo
              brand="redis"
              decorative
              variant="tile"
              width={16}
              height={16}
              className="h-6 w-6"
              imageClassName="h-4 w-4"
            />
            Redis
          </h2>
          <div className="mb-4 grid grid-cols-2 gap-2">
            <StatTile
              label="Memory"
              value={red?.used_memory_mb ? `${red.used_memory_mb} MB` : "-"}
              icon={<HardDrive size={14} />}
              color={(red?.used_memory_mb ?? 0) > 256 ? "text-(--warn)" : "text-(--good)"}
            />
            <StatTile
              label="Peak"
              value={red?.used_memory_peak_mb ? `${red.used_memory_peak_mb} MB` : "-"}
              icon={<Activity size={14} />}
            />
            <StatTile
              label="Clients"
              value={red?.connected_clients ?? "-"}
              icon={<Wifi size={14} />}
            />
            <StatTile label="Keys" value={red?.total_keys ?? "-"} icon={<Database size={14} />} />
          </div>

          {queueData.length > 0 && (
            <div>
              <h3 className={`${MONO_META} mb-2`}>Queue depths</h3>
              <div className="h-[120px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={queueData}>
                    <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_STROKE} />
                    <XAxis dataKey="name" tick={CHART_AXIS_TICK_SMALL} />
                    <YAxis tick={CHART_AXIS_TICK_SMALL} />
                    <Tooltip content={<ChartTooltip />} />
                    <Bar dataKey="depth" name="Jobs" radius={[4, 4, 0, 0]}>
                      {queueData.map((entry, i) => (
                        <Cell key={i} fill={queueColor(entry.depth)} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </section>
      </div>

      {/* Request metrics */}
      <section className={WSEC}>
        <h2 className={SEC_TITLE}>
          <Activity size={14} className="text-(--purple)" /> Request metrics (since startup)
        </h2>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile
            label="Total requests"
            value={(req?.total_requests ?? 0).toLocaleString()}
            icon={<Activity size={14} />}
          />
          <StatTile
            label="2xx OK"
            value={(req?.by_status?.["2xx"] ?? 0).toLocaleString()}
            icon={<CheckCircle size={14} />}
            color="text-(--good)"
          />
          <StatTile
            label="4xx client"
            value={(req?.by_status?.["4xx"] ?? 0).toLocaleString()}
            icon={<AlertTriangle size={14} />}
            color="text-(--warn)"
          />
          <StatTile
            label="Error rate"
            value={`${(req?.error_rate_percent ?? 0).toFixed(1)}%`}
            icon={<XCircle size={14} />}
            color={
              (req?.error_rate_percent ?? 0) > 5
                ? "text-(--bad)"
                : (req?.error_rate_percent ?? 0) > 2
                  ? "text-(--warn)"
                  : "text-(--good)"
            }
          />
        </div>
      </section>

      {/* Workers + top tables */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="overflow-hidden rounded-(--r) border border-(--line) bg-(--panel)">
          <div className="border-b border-(--line) px-[22px] py-[14px]">
            <h2 className="m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)">
              Worker health
            </h2>
          </div>
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-(--line)">
                <th className={`p-3 ${MICRO_LABEL}`}>Worker</th>
                <th className={`p-3 ${MICRO_LABEL}`}>Status</th>
                <th className={`p-3 ${MICRO_LABEL}`}>Jobs</th>
                <th className={`p-3 ${MICRO_LABEL}`}>Last seen</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-(--line)">
              {workers.length ? (
                workers.map((w) => (
                  <tr key={w.name} className="transition-colors hover:bg-(--paper)">
                    <td className="p-3 text-xs font-semibold text-(--t-1)">{w.name}</td>
                    <td className="p-3">
                      <span
                        className={`${CHIP} ${
                          w.status === "alive"
                            ? "text-(--good) bg-(--good-s)"
                            : w.status === "dead"
                              ? "text-(--bad) bg-(--bad-s)"
                              : "text-(--t-2) bg-(--paper)"
                        }`}
                      >
                        {w.status === "alive" ? <CheckCircle size={8} /> : <XCircle size={8} />}
                        {w.status}
                      </span>
                    </td>
                    <td className="p-3 text-xs text-(--t-2)">{w.jobs_processed ?? "-"}</td>
                    <td className="p-3 text-[11px] text-(--t-2)">
                      {w.age_seconds != null ? `${Math.round(w.age_seconds)}s ago` : "-"}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={4} className={`p-6 text-center ${MONO_META}`}>
                    No workers found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>

        <section className="overflow-hidden rounded-(--r) border border-(--line) bg-(--panel)">
          <div className="border-b border-(--line) px-[22px] py-[14px]">
            <h2 className="m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)">
              Top tables by size
            </h2>
          </div>
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-(--line)">
                <th className={`p-3 ${MICRO_LABEL}`}>Table</th>
                <th className={`p-3 text-right ${MICRO_LABEL}`}>Rows</th>
                <th className={`p-3 text-right ${MICRO_LABEL}`}>Size</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-(--line)">
              {(db?.top_tables || []).map((t) => (
                <tr key={t.table} className="transition-colors hover:bg-(--paper)">
                  <td className="p-3 font-(family-name:--mono) text-xs font-semibold text-(--t-1)">
                    {t.table}
                  </td>
                  <td className="p-3 text-right text-xs text-(--t-2)">
                    {t.rows?.toLocaleString() ?? "-"}
                  </td>
                  <td className="p-3 text-right text-xs text-(--t-2)">{t.size_mb} MB</td>
                </tr>
              ))}
              {!db?.top_tables?.length && (
                <tr>
                  <td colSpan={3} className={`p-6 text-center ${MONO_META}`}>
                    No table data
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
      </div>
    </>
  );
}
