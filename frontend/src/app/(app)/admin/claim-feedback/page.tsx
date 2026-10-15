"use client";

import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, MessageSquare, ThumbsDown, ThumbsUp } from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import { AdminInlineError } from "@/components/admin/AdminInlineError";
import { AdminTableSkeleton, AdminCardSkeleton } from "@/components/admin/AdminTableSkeleton";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import SignalDataTable, { type SignalDataTableColumn } from "@/components/signal/SignalDataTable";
import {
  CHART_AXIS_TICK_SMALL,
  CHART_GRID_STROKE,
  CHART_TOOLTIP_STYLE,
  CHART_CURSOR,
} from "@/components/ui/chartTokens";
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

/* ── Types ─────────────────────────────────────────────────────────── */

type FeedbackTotals = { agree: number; disagree: number; fixed: number };

type CategoryStat = {
  category: string;
  total: number;
  agree: number;
  disagree: number;
  fixed: number;
  disagree_rate: number;
};

type FlaggedClaim = {
  claim_key: string;
  claim_text: string;
  claim_category: string | null;
  disagree_count: number;
};

type DailyVolume = {
  date: string;
  agree: number;
  disagree: number;
  fixed: number;
};

type FeedbackAnalytics = {
  total_feedback: number;
  totals: FeedbackTotals;
  disagree_rate: number;
  categories: CategoryStat[];
  flagged_claims: FlaggedClaim[];
  daily_volume: DailyVolume[];
};

/* ── Constants ─────────────────────────────────────────────────────── */

const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const WSTAT = "rounded-[22px] border-0 bg-white px-4 py-3";
const WSTAT_VALUE =
  "font-(family-name:--disp) text-[20px] font-bold leading-none tracking-[-0.02em] text-(--t-1)";
const WSEC = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";
const SEC_TITLE =
  "m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)";
const INSET = "rounded-(--r-md) border-0 bg-[#EEF1F6] p-3";
const CHIP =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";

const WINDOWS = [
  { label: "7 d", value: 7 },
  { label: "30 d", value: 30 },
  { label: "90 d", value: 90 },
] as const;

const SERIES_COLORS = {
  agree: "var(--good)",
  disagree: "var(--bad)",
  fixed: "var(--link)",
};

/* ── Helpers ───────────────────────────────────────────────────────── */

function StatCard({
  icon,
  label,
  value,
  sub,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  sub?: string;
  color?: string;
}) {
  return (
    <div className={`${WSTAT} flex items-center gap-3`}>
      <div
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-(--r-md) bg-(--paper)"
        style={color ? { color } : undefined}
      >
        {icon}
      </div>
      <div className="min-w-0">
        <p className={MICRO_LABEL}>{label}</p>
        <p className={`${WSTAT_VALUE} mt-1`}>{value}</p>
        {sub ? <p className="mt-0.5 text-xs text-(--t-3)">{sub}</p> : null}
      </div>
    </div>
  );
}

function ChartTooltipContent({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div style={CHART_TOOLTIP_STYLE} className="px-3 py-2 text-xs">
      <p className="mb-1 font-semibold text-(--t-3)">{label}</p>
      {payload.map((p) => (
        <p key={p.name} className="flex items-center gap-1.5">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: p.color }}
          />
          <span className="capitalize text-(--t-2)">{p.name}</span>
          <span className="ml-auto font-semibold text-(--t-1)">{p.value}</span>
        </p>
      ))}
    </div>
  );
}

/* ── Main page ─────────────────────────────────────────────────────── */

export default function AdminClaimFeedbackPage() {
  const { getToken, isSignedIn } = useAuth();
  const { isLoading: isGuardLoading } = useAdminAccess();

  const [data, setData] = useState<FeedbackAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [days, setDays] = useState(30);

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) throw new Error("Not authenticated.");
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const loadData = useCallback(async () => {
    if (!isSignedIn) return;
    setLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`/api/admin/claim-feedback/analytics?days=${days}`, { headers });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load data.");
    } finally {
      setLoading(false);
    }
  }, [isSignedIn, getAuthHeaders, days]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  /* ── Loading / error ───────────────────────────────────────────── */

  const { setHeader } = useWorkspacePageHeader();
  useEffect(() => {
    setHeader({
      actions: (
        <div className="hidden gap-1 rounded-(--r-md) border-0 bg-[#EEF1F6] p-0.5 sm:flex">
          {WINDOWS.map((w) => (
            <button
              key={w.value}
              onClick={() => setDays(w.value)}
              className={`rounded-(--r-sm) px-3 py-1.5 font-(family-name:--mono) text-[11px] tracking-[0.04em] transition-colors ${
                days === w.value
                  ? "bg-(--panel) text-(--t-1) shadow-sm"
                  : "text-(--t-3) hover:text-(--t-1)"
              }`}
            >
              {w.label}
            </button>
          ))}
        </div>
      ),
    });
    return () => setHeader(null);
  }, [days, setHeader]);

  if (loading || isGuardLoading) {
    return (
      <>
        <DashboardPageIntro icon={MessageSquare} title="Claim feedback analytics" />
        <AdminCardSkeleton cards={4} />
        <AdminTableSkeleton rows={6} columns={4} />
      </>
    );
  }

  if (error) {
    return <AdminInlineError message={error} onRetry={loadData} />;
  }

  if (!data) return null;

  const { totals, disagree_rate, categories, flagged_claims, daily_volume } = data;

  const categoryColumns: SignalDataTableColumn<CategoryStat>[] = [
    {
      key: "category",
      header: "Category",
      renderCell: (cat) => <span className="font-semibold text-(--t-1)">{cat.category}</span>,
    },
    {
      key: "total",
      header: "Total",
      align: "right",
      renderCell: (cat) => <span className="tabular-nums text-(--t-1)">{cat.total}</span>,
    },
    {
      key: "agree",
      header: "Agree",
      align: "right",
      renderCell: (cat) => <span className="tabular-nums text-(--good)">{cat.agree}</span>,
    },
    {
      key: "disagree",
      header: "Disagree",
      align: "right",
      renderCell: (cat) => <span className="tabular-nums text-(--bad)">{cat.disagree}</span>,
    },
    {
      key: "fixed",
      header: "Fixed",
      align: "right",
      renderCell: (cat) => <span className="tabular-nums text-(--link)">{cat.fixed}</span>,
    },
    {
      key: "rate",
      header: "Disagree rate",
      align: "right",
      renderCell: (cat) => (
        <span
          className={`tabular-nums ${cat.disagree_rate >= 30 ? "font-semibold text-(--bad)" : "text-(--t-2)"}`}
        >
          {cat.disagree_rate}%
        </span>
      ),
    },
  ];

  /* ── Render ────────────────────────────────────────────────────── */

  return (
    <>
      {/* Header */}
      <DashboardPageIntro icon={MessageSquare} title="Claim feedback analytics">
        User acceptance signals on AI-generated audit findings
      </DashboardPageIntro>

      {/* Mobile duplicate of the `.top` window control (hidden at sm+). */}
      <div
        role="group"
        aria-label="Feedback window"
        className="flex gap-1 self-start rounded-(--r-md) border-0 bg-[#EEF1F6] p-0.5 sm:hidden"
      >
        {WINDOWS.map((w) => (
          <button
            key={w.value}
            onClick={() => setDays(w.value)}
            className={`rounded-(--r-sm) px-3 py-1.5 font-(family-name:--mono) text-[11px] tracking-[0.04em] transition-colors ${
              days === w.value
                ? "bg-(--panel) text-(--t-1) shadow-sm"
                : "text-(--t-3) hover:text-(--t-1)"
            }`}
          >
            {w.label}
          </button>
        ))}
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard
          icon={<MessageSquare size={18} />}
          label="Total feedback"
          value={data.total_feedback}
          sub={`Last ${days} days`}
        />
        <StatCard
          icon={<ThumbsUp size={18} />}
          label="Agrees"
          value={totals.agree}
          color="var(--good)"
        />
        <StatCard
          icon={<ThumbsDown size={18} />}
          label="Disagrees"
          value={totals.disagree}
          sub={`${disagree_rate}% disagree rate`}
          color="var(--bad)"
        />
        <StatCard
          icon={<CheckCircle2 size={18} />}
          label="Fixed"
          value={totals.fixed}
          color="var(--link)"
        />
      </div>

      {/* Daily volume chart */}
      <div className={WSEC}>
        <h2 className={SEC_TITLE}>Feedback volume</h2>
        {daily_volume.length > 0 ? (
          <div className="mt-4 h-[280px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={daily_volume}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_STROKE} />
                <XAxis
                  dataKey="date"
                  tick={CHART_AXIS_TICK_SMALL}
                  tickFormatter={(v: string) => v.slice(5)}
                />
                <YAxis tick={CHART_AXIS_TICK_SMALL} allowDecimals={false} />
                <Tooltip content={<ChartTooltipContent />} cursor={CHART_CURSOR} />
                <Area
                  type="monotone"
                  dataKey="agree"
                  stackId="1"
                  stroke={SERIES_COLORS.agree}
                  fill={SERIES_COLORS.agree}
                  fillOpacity={0.15}
                />
                <Area
                  type="monotone"
                  dataKey="disagree"
                  stackId="1"
                  stroke={SERIES_COLORS.disagree}
                  fill={SERIES_COLORS.disagree}
                  fillOpacity={0.15}
                />
                <Area
                  type="monotone"
                  dataKey="fixed"
                  stackId="1"
                  stroke={SERIES_COLORS.fixed}
                  fill={SERIES_COLORS.fixed}
                  fillOpacity={0.15}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="mt-4 text-sm text-(--t-2)">No feedback recorded in this period.</p>
        )}
      </div>

      {/* Two-col: Category breakdown + Flagged claims */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Category breakdown bar chart */}
        <div className={WSEC}>
          <h2 className={SEC_TITLE}>Disagree rate by category</h2>
          {categories.length > 0 ? (
            <div className="mt-4 h-[280px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={categories.slice(0, 10)} layout="vertical" margin={{ left: 10 }}>
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke={CHART_GRID_STROKE}
                    horizontal={false}
                  />
                  <XAxis type="number" tick={CHART_AXIS_TICK_SMALL} domain={[0, 100]} unit="%" />
                  <YAxis
                    type="category"
                    dataKey="category"
                    tick={CHART_AXIS_TICK_SMALL}
                    width={100}
                  />
                  <Tooltip content={<ChartTooltipContent />} cursor={CHART_CURSOR} />
                  <Bar dataKey="disagree_rate" radius={[0, 4, 4, 0]}>
                    {categories.slice(0, 10).map((cat) => (
                      <Cell
                        key={cat.category}
                        fill={cat.disagree_rate >= 30 ? "var(--bad)" : "var(--warn)"}
                        fillOpacity={0.7}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="mt-4 text-sm text-(--t-2)">No category data yet.</p>
          )}
        </div>

        {/* Flagged claims list */}
        <div className={WSEC}>
          <div className="flex items-center gap-2">
            <AlertTriangle size={14} className="text-(--warn)" />
            <h2 className={SEC_TITLE}>Frequently disagreed claims</h2>
          </div>
          {flagged_claims.length > 0 ? (
            <div className="mt-4 space-y-3">
              {flagged_claims.map((fc) => (
                <div key={fc.claim_key} className={INSET}>
                  <div className="flex items-start justify-between gap-2">
                    <p className="line-clamp-2 text-sm font-medium text-(--t-1)">{fc.claim_text}</p>
                    <span className={`${CHIP} shrink-0 text-(--bad) bg-(--bad-s)`}>
                      {fc.disagree_count} disagrees
                    </span>
                  </div>
                  {fc.claim_category ? (
                    <p className="mt-1 text-xs text-(--t-3)">{fc.claim_category}</p>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-4 text-sm text-(--t-2)">No frequently disagreed claims found.</p>
          )}
        </div>
      </div>

      {/* Category table */}
      {categories.length > 0 ? (
        <div>
          <h2 className={`${SEC_TITLE} mb-3`}>Feedback by category</h2>
          <SignalDataTable
            columns={categoryColumns}
            rows={categories}
            rowKey={(cat) => cat.category}
          />
        </div>
      ) : null}
    </>
  );
}
