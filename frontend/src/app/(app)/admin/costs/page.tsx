"use client";

import React, { useCallback, useEffect, useState } from "react";
import { DollarSign, Euro, TrendingUp, Cpu, BarChart3, Users, Building2 } from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { NativeSelect } from "@/components/ui/native-select";
import { AdminInlineError } from "@/components/admin/AdminInlineError";
import { AdminTableSkeleton, AdminCardSkeleton } from "@/components/admin/AdminTableSkeleton";
import { TIER_SHORT } from "@/constants/tiers";
import {
  CHART_AXIS_TICK_SMALL,
  CHART_GRID_STROKE,
  CHART_TOOLTIP_STYLE,
} from "@/components/ui/chartTokens";
import { formatAiModelName } from "@/lib/modelDisplay";
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

/* ── Types ──────────────────────────────────────────────────────── */

type CostSummary = {
  currency?: "USD";
  currency_policy?: CurrencyPolicy;
  current_month_cost: number;
  projected_month_end: number;
  avg_cost_per_audit: number;
  total_tokens_month: number;
  audit_count_month: number;
  prev_month_audit_count: number;
  top_model: string;
  top_model_cost: number;
};

type DailyCostEntry = {
  date: string;
  total_cost: number;
  total_tokens: number;
  audit_count: number;
  by_model: Record<string, number>;
};

type ModelCostEntry = {
  model: string;
  tokens: number;
  cost: number;
  audits: number;
  cost_per_1m_usd?: {
    input: number;
    output: number;
  };
};

type WorkspaceCostEntry = {
  workspace_id: number;
  workspace_name: string;
  cost: number;
  audits: number;
  tokens: number;
};

type UserCostEntry = {
  user_id: number;
  email: string;
  cost: number;
  audits: number;
  tokens: number;
};

type CurrencyPolicy = {
  display_currency: "USD";
};

type RequestedTierFilter = "all" | "fast" | "smart" | "deep_judgment";
type DebateProfileFilter = "all" | "high_confidence";

const REQUESTED_TIER_OPTIONS: Array<{ value: RequestedTierFilter; label: string }> = [
  { value: "all", label: "All modes" },
  { value: "fast", label: TIER_SHORT.fast },
  { value: "smart", label: TIER_SHORT.smart },
  { value: "deep_judgment", label: TIER_SHORT.deep_judgment },
];

const DEBATE_PROFILE_OPTIONS: Array<{ value: DebateProfileFilter; label: string }> = [
  { value: "all", label: "All profiles" },
  { value: "high_confidence", label: "High confidence" },
];

function formatRequestedTierLabel(value: RequestedTierFilter): string {
  return REQUESTED_TIER_OPTIONS.find((option) => option.value === value)?.label ?? "All modes";
}

function formatDebateProfileLabel(value: DebateProfileFilter): string {
  return DEBATE_PROFILE_OPTIONS.find((option) => option.value === value)?.label ?? "All profiles";
}

/* ── Design tokens ──────────────────────────────────────────────── */

const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const MONO_META = MICRO_LABEL.replace("uppercase ", "");
const WSEC = "rounded-(--r) border border-(--line) bg-(--panel) px-[22px] py-[18px]";
const SEC_TITLE =
  "m-0 mb-4 flex items-center gap-2 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)";

/* ── Color palette for charts ────────────────────────────────────── */

const MODEL_COLORS: Record<string, string> = {
  "gemini-2.5-flash": "var(--chart-2)",
  "gemini-2.5-pro": "var(--chart-1)",
  "gpt-5-nano": "var(--chart-3)",
  "gpt-5": "var(--chart-1)",
  "claude-sonnet-4-5": "var(--chart-4)",
  "claude-opus-4-6": "var(--chart-5)",
  unknown: "var(--chart-6)",
};

const BAR_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
  "var(--chart-6)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-6)",
  "var(--chart-2)",
];

/* ── Stat card (value-over-label `.wstat`) ──────────────────────── */

function StatCard({
  label,
  value,
  icon,
  subtext,
}: {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  subtext?: string;
}) {
  return (
    <div className={`${WSEC} flex items-center gap-3`}>
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-(--r-md) bg-(--paper) text-(--purple)">
        {icon}
      </div>
      <div className="min-w-0">
        <p className={MICRO_LABEL}>{label}</p>
        <p className="truncate font-(family-name:--disp) text-lg font-bold text-(--t-1)">{value}</p>
        {subtext && <p className="text-[10px] font-medium text-(--t-3)">{subtext}</p>}
      </div>
    </div>
  );
}

/* ── Custom tooltip for charts ──────────────────────────────────── */

const formatMoney = (value: number, currency: "EUR" | "USD") =>
  new Intl.NumberFormat(currency === "EUR" ? "en-IE" : "en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);

const formatAxisMoney = (value: number, currency: "EUR" | "USD") =>
  new Intl.NumberFormat(currency === "EUR" ? "en-IE" : "en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(value);

function CurrencyIcon({ currency, size }: { currency: "EUR" | "USD"; size: number }) {
  return currency === "USD" ? <DollarSign size={size} /> : <Euro size={size} />;
}

function ChartTooltip({
  active,
  payload,
  label,
  currency,
}: {
  active?: boolean;
  payload?: { name: string; value?: number; color?: string }[];
  label?: string;
  currency: "EUR" | "USD";
}) {
  if (!active || !payload?.length) return null;
  return (
    <div style={CHART_TOOLTIP_STYLE} className="px-3 py-2">
      <p className={`${MICRO_LABEL} mb-1.5`}>{label}</p>
      {payload.map((entry, i) => (
        <p key={i} className="text-xs font-semibold" style={{ color: entry.color }}>
          {entry.name}: {formatMoney(Number(entry.value ?? 0), currency)}
        </p>
      ))}
    </div>
  );
}

/* ── Main page ──────────────────────────────────────────────────── */

export default function AdminCostsDashboard() {
  const { getToken, isSignedIn } = useAuth();
  const { isLoading: isGuardLoading } = useAdminAccess();
  const { setHeader } = useWorkspacePageHeader();

  const [summary, setSummary] = useState<CostSummary | null>(null);
  const [dailySeries, setDailySeries] = useState<DailyCostEntry[]>([]);
  const [modelBreakdown, setModelBreakdown] = useState<ModelCostEntry[]>([]);
  const [topWorkspaces, setTopWorkspaces] = useState<WorkspaceCostEntry[]>([]);
  const [topUsers, setTopUsers] = useState<UserCostEntry[]>([]);
  const [displayCurrency, setDisplayCurrency] = useState<"USD">("USD");
  const [windowDays, setWindowDays] = useState(30);
  const [requestedTierFilter, setRequestedTierFilter] = useState<RequestedTierFilter>("all");
  const [debateProfileFilter, setDebateProfileFilter] = useState<DebateProfileFilter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) throw new Error("Not authenticated.");
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const buildCostQuery = useCallback(
    (params: Record<string, string | number>) => {
      const query = new URLSearchParams();
      Object.entries(params).forEach(([key, value]) => {
        query.set(key, String(value));
      });
      if (requestedTierFilter !== "all") {
        query.set("requested_tier", requestedTierFilter);
      }
      if (debateProfileFilter !== "all") {
        query.set("debate_profile", debateProfileFilter);
      }
      const encoded = query.toString();
      return encoded ? `?${encoded}` : "";
    },
    [debateProfileFilter, requestedTierFilter]
  );

  const loadAll = useCallback(async () => {
    if (!isSignedIn) return;
    setLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();

      const [sumRes, dailyRes, modelRes, wsRes, userRes] = await Promise.all([
        fetch(`/api/admin/costs/summary${buildCostQuery({})}`, { headers }),
        fetch(`/api/admin/costs/daily${buildCostQuery({ days: windowDays })}`, { headers }),
        fetch(`/api/admin/costs/by-model${buildCostQuery({ window_days: windowDays })}`, {
          headers,
        }),
        fetch(
          `/api/admin/costs/by-workspace${buildCostQuery({ window_days: windowDays, limit: 10 })}`,
          { headers }
        ),
        fetch(`/api/admin/costs/by-user${buildCostQuery({ window_days: windowDays, limit: 10 })}`, {
          headers,
        }),
      ]);

      if (!sumRes.ok) throw new Error("Failed to load cost summary.");

      const summaryPayload = (await sumRes.json()) as CostSummary;
      setSummary(summaryPayload);
      setDisplayCurrency("USD");
      if (dailyRes.ok) {
        const d = await dailyRes.json();
        setDailySeries(d.series || []);
      }
      if (modelRes.ok) {
        const m = await modelRes.json();
        setModelBreakdown(m.models || []);
      }
      if (wsRes.ok) {
        const w = await wsRes.json();
        setTopWorkspaces(w.workspaces || []);
      }
      if (userRes.ok) {
        const u = await userRes.json();
        setTopUsers(u.users || []);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load cost data.");
    } finally {
      setLoading(false);
    }
  }, [buildCostQuery, getAuthHeaders, isSignedIn, windowDays]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  /* Page-scoped `.top` action: the reporting-window segmented control. */
  useEffect(() => {
    setHeader({
      actions: (
        <div
          role="group"
          aria-label="Cost window"
          className="hidden items-center gap-0.5 rounded-(--r-md) border border-(--line) bg-(--paper) p-0.5 sm:flex"
        >
          {[7, 30, 90].map((days) => (
            <button
              key={days}
              type="button"
              onClick={() => setWindowDays(days)}
              className={`rounded-(--r-sm) px-2.5 py-1 font-(family-name:--mono) text-[11px] tracking-[0.04em] transition-colors ${
                windowDays === days
                  ? "bg-(--panel) text-(--t-1) shadow-sm"
                  : "text-(--t-3) hover:text-(--t-1)"
              }`}
            >
              {days}d
            </button>
          ))}
        </div>
      ),
    });
    return () => setHeader(null);
  }, [windowDays, setHeader]);

  if (loading || isGuardLoading) {
    return (
      <>
        <DashboardPageIntro icon={DollarSign} title="AI cost monitor" />
        <AdminCardSkeleton cards={4} />
        <AdminTableSkeleton rows={8} columns={5} />
      </>
    );
  }

  if (error) {
    return <AdminInlineError message={error} onRetry={loadAll} />;
  }

  return (
    <>
      <DashboardPageIntro icon={CurrencyIconComponent(displayCurrency)} title="AI cost monitor">
        Real-time AI spend monitoring, model cost breakdown, and top consumer analysis. AI spend
        tracked in USD.
      </DashboardPageIntro>

      {/* Mobile duplicate of the `.top` cost-window control (hidden at sm+). */}
      <div
        role="group"
        aria-label="Cost window"
        className="flex items-center gap-0.5 self-start rounded-(--r-md) border border-(--line) bg-(--paper) p-0.5 sm:hidden"
      >
        {[7, 30, 90].map((days) => (
          <button
            key={days}
            type="button"
            onClick={() => setWindowDays(days)}
            className={`rounded-(--r-sm) px-2.5 py-1 font-(family-name:--mono) text-[11px] tracking-[0.04em] transition-colors ${
              windowDays === days
                ? "bg-(--panel) text-(--t-1) shadow-sm"
                : "text-(--t-3) hover:text-(--t-1)"
            }`}
          >
            {days}d
          </button>
        ))}
      </div>

      {/* Server-side scope filters */}
      <div className={`${WSEC} flex flex-wrap items-end gap-4`}>
        <div className="min-w-[180px] flex-1">
          <label className={MICRO_LABEL} htmlFor="costs-tier-filter">
            Requested tier
          </label>
          <NativeSelect
            id="costs-tier-filter"
            variant="auth"
            value={requestedTierFilter}
            onChange={(event) => setRequestedTierFilter(event.target.value as RequestedTierFilter)}
            className="mt-1.5"
          >
            {REQUESTED_TIER_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="min-w-[180px] flex-1">
          <label className={MICRO_LABEL} htmlFor="costs-profile-filter">
            Debate profile
          </label>
          <NativeSelect
            id="costs-profile-filter"
            variant="auth"
            value={debateProfileFilter}
            onChange={(event) => setDebateProfileFilter(event.target.value as DebateProfileFilter)}
            className="mt-1.5"
          >
            {DEBATE_PROFILE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </NativeSelect>
        </div>
        {(requestedTierFilter !== "all" || debateProfileFilter !== "all") && (
          <p className={MONO_META}>
            Filtered to {formatRequestedTierLabel(requestedTierFilter)}
            {debateProfileFilter !== "all"
              ? ` · ${formatDebateProfileLabel(debateProfileFilter)}`
              : ""}
          </p>
        )}
      </div>

      {/* KPI bar */}
      {summary && (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <StatCard
            label="Month-to-date"
            value={formatMoney(summary.current_month_cost, displayCurrency)}
            icon={<CurrencyIcon currency={displayCurrency} size={18} />}
            subtext={`${summary.audit_count_month} audits`}
          />
          <StatCard
            label="Projected EOM"
            value={formatMoney(summary.projected_month_end, displayCurrency)}
            icon={<TrendingUp size={18} />}
            subtext="Linear projection"
          />
          <StatCard
            label="Avg cost / audit"
            value={formatMoney(summary.avg_cost_per_audit, displayCurrency)}
            icon={<BarChart3 size={18} />}
            subtext={`${(summary.total_tokens_month / 1000).toFixed(0)}K tokens`}
          />
          <StatCard
            label="Top model"
            value={formatAiModelName(summary.top_model)}
            icon={<Cpu size={18} />}
            subtext={`${formatMoney(summary.top_model_cost, displayCurrency)} this month`}
          />
        </div>
      )}

      {/* Daily spend chart */}
      <section className={WSEC}>
        <h2 className={SEC_TITLE}>
          Daily AI spend ({displayCurrency}), {windowDays} days
        </h2>
        <div className="h-[300px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={dailySeries}>
              <defs>
                <linearGradient id="costGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.26} />
                  <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0.03} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_STROKE} />
              <XAxis
                dataKey="date"
                tick={CHART_AXIS_TICK_SMALL}
                tickFormatter={(v) => v.slice(5)}
                axisLine={false}
              />
              <YAxis
                tick={CHART_AXIS_TICK_SMALL}
                tickFormatter={(value) => formatAxisMoney(Number(value ?? 0), displayCurrency)}
                axisLine={false}
              />
              <Tooltip content={<ChartTooltip currency={displayCurrency} />} />
              <Area
                type="monotone"
                dataKey="total_cost"
                stroke="var(--chart-1)"
                strokeWidth={2}
                fill="url(#costGradient)"
                name="Cost"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* Model breakdown + top workspaces */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className={WSEC}>
          <h2 className={SEC_TITLE}>Cost by model ({displayCurrency})</h2>
          <div className="h-[280px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={modelBreakdown} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_STROKE} />
                <XAxis
                  type="number"
                  tick={CHART_AXIS_TICK_SMALL}
                  tickFormatter={(value) => formatAxisMoney(Number(value ?? 0), displayCurrency)}
                  axisLine={false}
                />
                <YAxis
                  dataKey="model"
                  type="category"
                  width={130}
                  tick={{ ...CHART_AXIS_TICK_SMALL, fill: "var(--foreground)" }}
                  tickFormatter={(value) => formatAiModelName(String(value ?? ""))}
                  axisLine={false}
                />
                <Tooltip content={<ChartTooltip currency={displayCurrency} />} />
                <Bar dataKey="cost" name="Cost" radius={[0, 6, 6, 0]}>
                  {modelBreakdown.map((entry, i) => (
                    <Cell
                      key={entry.model}
                      fill={MODEL_COLORS[entry.model] ?? BAR_COLORS[i % BAR_COLORS.length]}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className={WSEC}>
          <h2 className={SEC_TITLE}>
            <Building2 size={14} className="text-(--purple)" /> Top workspaces by cost (
            {displayCurrency})
          </h2>
          <div className="space-y-0">
            {topWorkspaces.length ? (
              topWorkspaces.map((ws, i) => (
                <div
                  key={ws.workspace_id}
                  className="flex items-center gap-3 border-b border-(--line) px-3 py-2.5 transition-colors last:border-0 hover:bg-(--paper)"
                >
                  <span className={`w-5 ${MICRO_LABEL}`}>{i + 1}</span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-semibold text-(--t-1)">
                      {ws.workspace_name}
                    </p>
                    <p className="text-[10px] text-(--t-3)">
                      {ws.audits} audits · {(ws.tokens / 1000).toFixed(0)}K tokens
                    </p>
                  </div>
                  <span className="font-(family-name:--mono) text-sm font-semibold text-(--purple)">
                    {formatMoney(ws.cost, displayCurrency)}
                  </span>
                </div>
              ))
            ) : (
              <p className={`py-4 text-center ${MONO_META}`}>No workspace data</p>
            )}
          </div>
        </section>
      </div>

      {/* Top users */}
      <section className="overflow-hidden rounded-(--r) border border-(--line) bg-(--panel)">
        <div className="border-b border-(--line) px-[22px] py-[14px]">
          <h2 className="m-0 flex items-center gap-2 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)">
            <Users size={14} className="text-(--purple)" /> Top users by AI cost ({displayCurrency})
          </h2>
        </div>
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-(--line)">
              <th className={`p-4 ${MICRO_LABEL}`}>#</th>
              <th className={`p-4 ${MICRO_LABEL}`}>User</th>
              <th className={`p-4 ${MICRO_LABEL}`}>Audits</th>
              <th className={`p-4 ${MICRO_LABEL}`}>Tokens</th>
              <th className={`p-4 text-right ${MICRO_LABEL}`}>Cost ({displayCurrency})</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-(--line)">
            {topUsers.length ? (
              topUsers.map((u, i) => (
                <tr key={u.user_id} className="transition-colors hover:bg-(--paper)">
                  <td className="p-4 text-xs font-semibold text-(--t-3)">{i + 1}</td>
                  <td className="p-4 text-sm text-(--t-1)">{u.email}</td>
                  <td className="p-4 text-xs text-(--t-2)">{u.audits}</td>
                  <td className="p-4 text-xs text-(--t-2)">{(u.tokens / 1000).toFixed(0)}K</td>
                  <td className="p-4 text-right font-(family-name:--mono) text-sm font-semibold text-(--purple)">
                    {formatMoney(u.cost, displayCurrency)}
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={5} className={`p-8 text-center ${MONO_META}`}>
                  No user cost data
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </>
  );
}

function CurrencyIconComponent(currency: "EUR" | "USD") {
  return currency === "USD" ? DollarSign : Euro;
}
