"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Cpu,
  ShieldAlert,
  RefreshCw,
  AlertTriangle,
  Layout,
  Database,
  Search,
  Zap,
  Terminal,
  Activity,
  Globe,
  Clock,
  DollarSign,
  ScrollText,
  Eye,
} from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import { ClientSafeDate } from "@/lib/dateFormat";
import Button from "@/components/ui/Button";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { NativeSelect } from "@/components/ui/native-select";
import TrendBadge from "@/components/admin/charts/TrendBadge";
import MetricSparkline from "@/components/admin/charts/MetricSparkline";
import MetricLineChart from "@/components/admin/charts/MetricLineChart";
import MetricBarChart from "@/components/admin/charts/MetricBarChart";
import { formatAiModelName } from "@/lib/modelDisplay";

type SparkData = { date: string; value: number }[];

/* -------------------------------------------------------------------------- */
/*  Design tokens                                                              */
/* -------------------------------------------------------------------------- */

const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const MONO_META = MICRO_LABEL.replace("uppercase ", "");
const SLINK =
  "flex items-center gap-1 text-[12.5px] font-semibold text-(--link) transition-colors hover:text-(--t-1)";
const WSTAT = "rounded-[22px] border-0 bg-white px-4 py-3";
const WSTAT_VALUE =
  "font-(family-name:--disp) text-[24px] font-bold leading-none tracking-[-0.02em] text-(--t-1)";
const WSEC = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";
const SEC_TITLE =
  "m-0 flex items-center gap-2 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)";
const INSET = "rounded-(--r-md) border-0 bg-[#EEF1F6] p-4";
const CHIP =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";
const WINPUT =
  "field-focus-ring h-9 w-full rounded-(--r-md) border-0 bg-[#EEF1F6] px-[10px] text-[12.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6]";
const SKEL = "animate-pulse rounded-(--r-sm) bg-(--line-2)";

const StatCard = ({
  title,
  value,
  icon,
  subtitle,
  trendPct,
  sparkData,
  sparkColor,
}: {
  title: string;
  value: string;
  icon: React.ReactNode;
  subtitle?: string;
  trendPct?: number | null;
  sparkData?: SparkData;
  sparkColor?: string;
}) => (
  <div className={WSTAT}>
    <div className="mb-2 flex items-center justify-between">
      <p className={MICRO_LABEL}>{title}</p>
      <div className="text-(--t-3)">{icon}</div>
    </div>
    <div className="flex items-end justify-between gap-3">
      <div className="min-w-0">
        <h3 className={WSTAT_VALUE}>{value}</h3>
        <div className="mt-2 flex items-center gap-2">
          {trendPct !== undefined && <TrendBadge changePct={trendPct} />}
          {subtitle && <p className={`${MONO_META} truncate`}>{subtitle}</p>}
        </div>
      </div>
      {sparkData && sparkData.length > 1 && (
        <MetricSparkline
          data={sparkData}
          color={sparkColor}
          height={36}
          className="w-24 shrink-0"
        />
      )}
    </div>
  </div>
);

const TokenUsageRow = ({
  model,
  tokens,
  cost,
  audits,
}: {
  model: string;
  tokens: string;
  cost: string;
  audits: number;
}) => (
  <div className="grid grid-cols-4 gap-4 rounded-(--r-sm) border-b border-(--line) px-4 py-3 text-xs last:border-0 hover:bg-(--paper)">
    <div className="flex items-center gap-2 font-semibold text-(--t-1)">
      <div className="h-1.5 w-1.5 shrink-0 rounded-full bg-(--purple)" />
      {formatAiModelName(model)}
    </div>
    <div className="tabular-nums text-(--t-2)">{tokens}</div>
    <div className="tabular-nums text-(--t-2)">{audits}</div>
    <div className="font-semibold tabular-nums text-(--purple)">{cost}</div>
  </div>
);

type AdminMetrics = {
  monthly_recurring_revenue: number;
  total_api_costs: number;
  ai_cost_consumed_30d: number;
  ai_cost_consumed_total: number;
  avg_ai_cost_per_audit_30d: number;
  net_profit_margin: number;
  total_users: number;
  active_subscriptions: number;
  audits_last_30_days: number;
  total_audits: number;
  ai_cost_currency: "USD";
};

type TokenUsageEntry = {
  model: string;
  tokens: number;
  cost: number;
  audits: number;
};

type TokenUsageResponse = {
  window_days: number;
  total_tokens: number;
  total_cost: number;
  entries: TokenUsageEntry[];
  currency: "USD";
};

type TimeSeriesPoint = { date: string; value: number };
type PeriodSummary = { current: number; previous_period: number; change_pct: number | null };
type TimeSeriesResponse = {
  period: string;
  series: Record<string, TimeSeriesPoint[]>;
  summary: Record<string, PeriodSummary>;
};

type OperationStatus = {
  fallback_model_enabled: boolean;
  pricing_v2_enabled: boolean;
  credit_engine_v2_enabled: boolean;
  pricing_v2_shadow_mode: boolean;
  cache_refresh_requested_at: string | null;
};

type CacheMetadataResponse = {
  url: string;
  provider: string;
  tier: string;
  cached_at: string | null;
  content_hash: string | null;
  etag: string | null;
  last_modified: string | null;
  audit_id?: number | null;
};

type RecentActionEntry = {
  id: number;
  admin_user_id: number | null;
  admin_email: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
};

type SignalWarehouseHealthResponse = {
  total_signal_audit_snapshots: number;
  total_signal_citation_events: number;
  total_signal_entity_observations: number;
  total_signal_remediation_outcomes: number;
  total_benchmark_cohort_aggregates: number;
  total_proprietary_scores: number;
  historical_project_audits: number;
  audits_with_signal_snapshots: number;
  backfill_coverage_pct: number;
  last_ingested_at: string | null;
};

type SignalWarehouseBackfillResponse = {
  job_id: string;
  status: string;
  dry_run: boolean;
  audits_processed: number;
  batches_processed: number;
  rows_inserted: number;
  cohort_rows_written: number;
  errors: string[];
};

// MRR is summed from the plan catalogue's monthly_price_usd, so it is USD.
const formatUsdWhole = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);

const formatUsdWithCents = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);

export default function AdminOverviewPage() {
  const { getToken, isSignedIn } = useAuth();
  const { isAdmin, isLoading: isGuardLoading } = useAdminAccess();
  const { setHeader } = useWorkspacePageHeader();

  const [metrics, setMetrics] = useState<AdminMetrics | null>(null);
  const [tokenUsage, setTokenUsage] = useState<TokenUsageResponse | null>(null);
  const [operations, setOperations] = useState<OperationStatus | null>(null);
  const [timeseries, setTimeseries] = useState<TimeSeriesResponse | null>(null);
  const [tsPeriod, setTsPeriod] = useState<string>("30d");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isUpdatingOps, setIsUpdatingOps] = useState(false);
  const [cacheLookupError, setCacheLookupError] = useState("");
  const [cacheLookupResult, setCacheLookupResult] = useState<CacheMetadataResponse | null>(null);
  const [cacheLookupAuditId, setCacheLookupAuditId] = useState("");
  const [cacheLookupUrl, setCacheLookupUrl] = useState("");
  const [cacheLookupProvider, setCacheLookupProvider] = useState("google");
  const [cacheLookupTier, setCacheLookupTier] = useState("standard");
  const [isCacheLookupLoading, setIsCacheLookupLoading] = useState(false);
  const [recentActions, setRecentActions] = useState<RecentActionEntry[]>([]);
  const [signalWarehouseHealth, setSignalWarehouseHealth] =
    useState<SignalWarehouseHealthResponse | null>(null);
  const [signalWarehouseError, setSignalWarehouseError] = useState("");
  const [signalBackfillResult, setSignalBackfillResult] =
    useState<SignalWarehouseBackfillResponse | null>(null);
  const [isSignalBackfillRunning, setIsSignalBackfillRunning] = useState(false);

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to access admin data.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const loadSignalWarehouseHealth = useCallback(async (headers: HeadersInit) => {
    try {
      const response = await fetch("/api/admin/signal-warehouse/health", { headers });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load signal warehouse health.");
      }
      const payload = (await response.json()) as SignalWarehouseHealthResponse;
      setSignalWarehouseHealth(payload);
      setSignalWarehouseError("");
    } catch (err) {
      setSignalWarehouseHealth(null);
      setSignalWarehouseError(
        err instanceof Error ? err.message : "Unable to load signal warehouse health."
      );
    }
  }, []);

  const loadAdminData = useCallback(async () => {
    if (!isSignedIn) {
      return;
    }
    setIsLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const [metricsResponse, tokenResponse, opsResponse, tsResponse] = await Promise.all([
        fetch("/api/admin/metrics", { headers }),
        fetch("/api/admin/token-usage", { headers }),
        fetch("/api/admin/operations", { headers }),
        fetch(`/api/admin/metrics/timeseries?period=${tsPeriod}`, { headers }),
      ]);

      if (!metricsResponse.ok) {
        const payload = await metricsResponse.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load admin metrics.");
      }
      if (!tokenResponse.ok) {
        const payload = await tokenResponse.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load token usage.");
      }
      if (!opsResponse.ok) {
        const payload = await opsResponse.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load operational controls.");
      }

      const [metricsPayload, tokenPayload, opsPayload] = await Promise.all([
        metricsResponse.json() as Promise<AdminMetrics>,
        tokenResponse.json() as Promise<TokenUsageResponse>,
        opsResponse.json() as Promise<OperationStatus>,
      ]);
      setMetrics(metricsPayload);
      setTokenUsage(tokenPayload);
      setOperations(opsPayload);
      await loadSignalWarehouseHealth(headers);

      if (tsResponse.ok) {
        const tsPayload = (await tsResponse.json()) as TimeSeriesResponse;
        setTimeseries(tsPayload);
      }

      /* Fetch recent admin actions (non-blocking) */
      try {
        const actionsRes = await fetch("/api/admin/action-logs?page=1&page_size=10", { headers });
        if (actionsRes.ok) {
          const actionsPayload = await actionsRes.json();
          setRecentActions(actionsPayload.items ?? []);
        }
      } catch {
        /* non-critical, widget is supplementary */
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load admin data.");
    } finally {
      setIsLoading(false);
    }
  }, [getAuthHeaders, isSignedIn, loadSignalWarehouseHealth, tsPeriod]);

  useEffect(() => {
    loadAdminData();
  }, [loadAdminData]);

  const handleCacheRefresh = async () => {
    setIsUpdatingOps(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/admin/operations/cache-refresh", {
        method: "POST",
        headers,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to request cache refresh.");
      }
      const payload = (await response.json()) as OperationStatus;
      setOperations(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update operational controls.");
    } finally {
      setIsUpdatingOps(false);
    }
  };

  const handleFallbackToggle = async () => {
    if (!operations) {
      return;
    }
    setIsUpdatingOps(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/admin/operations/fallback-model", {
        method: "POST",
        headers: {
          ...headers,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ enabled: !operations.fallback_model_enabled }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to update fallback model.");
      }
      const payload = (await response.json()) as OperationStatus;
      setOperations(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update operational controls.");
    } finally {
      setIsUpdatingOps(false);
    }
  };

  const handleCacheLookup = async () => {
    setCacheLookupError("");
    setIsCacheLookupLoading(true);
    setCacheLookupResult(null);
    try {
      const headers = await getAuthHeaders();
      const params = new URLSearchParams();
      if (cacheLookupAuditId.trim()) {
        params.set("audit_id", cacheLookupAuditId.trim());
      } else {
        if (!cacheLookupUrl.trim()) {
          throw new Error("Enter a URL or an audit ID to lookup cache metadata.");
        }
        params.set("url", cacheLookupUrl.trim());
        params.set("provider", cacheLookupProvider);
        params.set("tier", cacheLookupTier);
      }

      const response = await fetch(`/api/admin/cache-metadata?${params.toString()}`, { headers });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load cache metadata.");
      }
      const payload = (await response.json()) as CacheMetadataResponse;
      setCacheLookupResult(payload);
    } catch (err) {
      setCacheLookupError(err instanceof Error ? err.message : "Unable to load cache metadata.");
    } finally {
      setIsCacheLookupLoading(false);
    }
  };

  const handleSignalBackfill = async (dryRun: boolean) => {
    setSignalWarehouseError("");
    setIsSignalBackfillRunning(true);
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/admin/signal-warehouse/backfill", {
        method: "POST",
        headers: {
          ...headers,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ dry_run: dryRun }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to trigger signal warehouse backfill.");
      }
      const payload = (await response.json()) as SignalWarehouseBackfillResponse;
      setSignalBackfillResult(payload);
      await loadSignalWarehouseHealth(headers);
    } catch (err) {
      setSignalWarehouseError(
        err instanceof Error ? err.message : "Unable to trigger signal warehouse backfill."
      );
    } finally {
      setIsSignalBackfillRunning(false);
    }
  };

  const controlsDisabled = !isAdmin || isUpdatingOps || isLoading || isGuardLoading;
  const cacheLookupDisabled = !isAdmin || isCacheLookupLoading || isLoading || isGuardLoading;
  const signalControlsDisabled = !isAdmin || isSignalBackfillRunning || isLoading || isGuardLoading;
  const systemStatusLabel = isAdmin ? "Admin controls available" : "Admin access required";
  const totalSignalFactRows = signalWarehouseHealth
    ? signalWarehouseHealth.total_signal_audit_snapshots +
      signalWarehouseHealth.total_signal_citation_events +
      signalWarehouseHealth.total_signal_entity_observations +
      signalWarehouseHealth.total_signal_remediation_outcomes
    : 0;

  /* Page-scoped actions live in `.top` (ledger §3.5 amendment): the period
     segmented control and the global refresh. Icon-only refresh keeps the
     bar under the 64px contract at narrow widths. */
  useEffect(() => {
    setHeader({
      actions: (
        <>
          <div
            role="group"
            aria-label="Timeseries period"
            className="hidden items-center gap-0.5 rounded-(--r-md) border-0 bg-[#EEF1F6] p-0.5 sm:flex"
          >
            {(["7d", "30d", "90d"] as const).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setTsPeriod(p)}
                className={`rounded-(--r-sm) px-2.5 py-1 font-(family-name:--mono) text-[11px] tracking-[0.04em] transition-colors ${
                  tsPeriod === p
                    ? "bg-(--panel) text-(--t-1) shadow-sm"
                    : "text-(--t-3) hover:text-(--t-1)"
                }`}
              >
                {p}
              </button>
            ))}
          </div>
          <Button
            variant="ghost"
            onClick={loadAdminData}
            disabled={isLoading}
            aria-label="Refresh"
            title="Refresh"
            className="h-8 w-8 p-0"
          >
            <RefreshCw size={14} className={isLoading ? "animate-spin" : ""} />
          </Button>
        </>
      ),
    });
    return () => setHeader(null);
  }, [isLoading, loadAdminData, setHeader, tsPeriod]);

  return (
    <>
      <DashboardPageIntro icon={Layout} title="Platform overview">
        Monitor platform performance, USD AI spend, and active subscriptions. AI spend is tracked in
        USD.
      </DashboardPageIntro>

      {/* Mobile duplicate of the `.top` period control (hidden at sm+). */}
      <div
        role="group"
        aria-label="Timeseries period"
        className="flex items-center gap-0.5 self-start rounded-(--r-md) border-0 bg-[#EEF1F6] p-0.5 sm:hidden"
      >
        {(["7d", "30d", "90d"] as const).map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => setTsPeriod(p)}
            className={`rounded-(--r-sm) px-2.5 py-1 font-(family-name:--mono) text-[11px] tracking-[0.04em] transition-colors ${
              tsPeriod === p
                ? "bg-(--panel) text-(--t-1) shadow-sm"
                : "text-(--t-3) hover:text-(--t-1)"
            }`}
          >
            {p}
          </button>
        ))}
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle size={16} />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {/* KPI cards */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="SaaS revenue (MRR)"
          value={metrics ? formatUsdWhole(metrics.monthly_recurring_revenue) : "-"}
          icon={<DollarSign size={16} />}
          subtitle={metrics ? `${metrics.active_subscriptions} active subscriptions` : undefined}
        />
        <StatCard
          title="AI spend (30d)"
          value={
            metrics
              ? formatUsdWithCents(metrics.ai_cost_consumed_30d ?? metrics.total_api_costs)
              : "-"
          }
          icon={<Cpu size={16} />}
          subtitle={metrics ? `${metrics.audits_last_30_days} total assessments` : undefined}
          trendPct={timeseries?.summary?.cost?.change_pct}
          sparkData={timeseries?.series?.cost}
          sparkColor="var(--bad)"
        />
        <StatCard
          title="AI spend / audit"
          value={metrics ? formatUsdWithCents(metrics.avg_ai_cost_per_audit_30d ?? 0) : "-"}
          icon={<Zap size={16} />}
          subtitle={
            metrics
              ? `Lifetime: ${formatUsdWithCents(metrics.ai_cost_consumed_total ?? 0)}`
              : undefined
          }
        />
        <StatCard
          title="Profit margin"
          value={metrics ? `${metrics.net_profit_margin.toFixed(1)}%` : "-"}
          icon={<Activity size={16} />}
          subtitle={metrics ? `${metrics.total_users} total users` : undefined}
        />
      </div>

      {/* Charts */}
      {timeseries && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <section className={WSEC}>
            <div className="mb-4 flex items-center justify-between">
              <h3 className={SEC_TITLE}>
                <Activity size={14} className="text-(--purple)" /> Audit activity
              </h3>
              {timeseries.summary.audits && (
                <TrendBadge changePct={timeseries.summary.audits.change_pct} />
              )}
            </div>
            <MetricBarChart
              data={timeseries.series.audits ?? []}
              label="Assessments"
              color="var(--purple)"
            />
          </section>

          <section className={WSEC}>
            <div className="mb-4 flex items-center justify-between">
              <h3 className={SEC_TITLE}>
                <Cpu size={14} className="text-(--bad)" /> AI spend trend
              </h3>
              {timeseries.summary.cost && (
                <TrendBadge changePct={timeseries.summary.cost.change_pct} />
              )}
            </div>
            <MetricLineChart
              data={timeseries.series.cost ?? []}
              label="Spend"
              color="var(--bad)"
              formatValue={(v) => formatUsdWithCents(v)}
            />
          </section>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* AI model usage */}
        <section className={WSEC}>
          <div className="mb-5 flex items-center justify-between">
            <h3 className={SEC_TITLE}>
              <Cpu size={14} className="text-(--purple)" /> Model usage metrics
            </h3>
            <span className={`${CHIP} text-(--purple) bg-(--purple-s)`}>Live</span>
          </div>

          <div className={`grid grid-cols-4 gap-4 px-4 py-2 ${MICRO_LABEL}`}>
            <span>Model</span>
            <span>Tokens</span>
            <span>Audits</span>
            <span>Cost</span>
          </div>

          <div className="mt-2 space-y-1">
            {tokenUsage?.entries?.length ? (
              tokenUsage.entries.map((entry) => (
                <TokenUsageRow
                  key={entry.model}
                  model={entry.model}
                  tokens={entry.tokens.toLocaleString()}
                  audits={entry.audits}
                  cost={formatUsdWithCents(entry.cost)}
                />
              ))
            ) : tokenUsage ? (
              <div className="flex flex-col items-center justify-center rounded-[22px] border-0 bg-[#EEF1F6] py-12">
                <Activity size={24} className="mb-2 text-(--t-3)" />
                <p className={MONO_META}>No usage data available.</p>
              </div>
            ) : (
              <div className="space-y-2 py-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className={`${SKEL} h-9 w-full`} />
                ))}
              </div>
            )}
          </div>

          <div className="mt-5 flex items-center justify-between border-t border-(--line) pt-4">
            <p className={MONO_META}>
              {tokenUsage
                ? `${tokenUsage.total_tokens.toLocaleString()} total tokens across ${tokenUsage.window_days} days.`
                : "Loading usage statistics..."}
            </p>
            {tokenUsage && (
              <span className="font-semibold tabular-nums text-(--purple)">
                {formatUsdWithCents(tokenUsage.total_cost)}
              </span>
            )}
          </div>
        </section>

        {/* System status */}
        <section className={WSEC}>
          <h3 className={`${SEC_TITLE} mb-5`}>
            <ShieldAlert size={14} className="text-(--good)" /> System status
          </h3>

          <div className="space-y-5">
            <div className="flex items-center justify-between rounded-[14px] border-0 bg-(--good-s) px-4 py-3">
              <span className={`${CHIP} text-(--good)`}>
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-(--good)" />
                {systemStatusLabel}
              </span>
              <Activity size={16} className="text-(--good)" />
            </div>

            <div className={`flex items-center gap-2 ${MONO_META}`}>
              <Clock size={12} />
              {operations?.cache_refresh_requested_at ? (
                <>
                  <span className={MICRO_LABEL}>Last cache refresh</span>
                  <ClientSafeDate date={operations.cache_refresh_requested_at} />
                </>
              ) : (
                <>
                  <span className={MICRO_LABEL}>Cache status</span> healthy
                </>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3">
              <Button variant="ghost" disabled={controlsDisabled} onClick={handleCacheRefresh}>
                <RefreshCw size={14} className={isUpdatingOps ? "animate-spin" : ""} />
                Flush cache
              </Button>
              <Button
                variant={operations?.fallback_model_enabled ? "danger" : "ghost"}
                disabled={controlsDisabled}
                onClick={handleFallbackToggle}
              >
                <AlertTriangle size={14} />
                {operations?.fallback_model_enabled ? "Disable fallback" : "Enable model fallback"}
              </Button>
            </div>

            {!isAdmin ? (
              <Alert variant="warning">
                <Terminal size={14} />
                <AlertDescription>Admin access required to use controls.</AlertDescription>
              </Alert>
            ) : null}
          </div>
        </section>
      </div>

      {/* Signal warehouse health */}
      <section className={WSEC}>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-1.5">
            <h3 className={SEC_TITLE}>
              <Database size={14} className="text-(--purple)" /> Signal warehouse health
            </h3>
            <p className="text-xs text-(--t-3)">
              Monitor warehouse ingest coverage and trigger replay-safe backfills.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="ghost"
              disabled={signalControlsDisabled}
              onClick={() => void handleSignalBackfill(true)}
            >
              <RefreshCw size={14} className={isSignalBackfillRunning ? "animate-spin" : ""} />
              Dry run
            </Button>
            <Button
              variant="primary"
              disabled={signalControlsDisabled}
              onClick={() => void handleSignalBackfill(false)}
            >
              <Database size={14} />
              Backfill
            </Button>
          </div>
        </div>

        {signalWarehouseError ? (
          <Alert variant="destructive" className="mt-4">
            <AlertDescription>{signalWarehouseError}</AlertDescription>
          </Alert>
        ) : null}

        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div className={INSET}>
            <p className={MICRO_LABEL}>Total fact rows</p>
            <p className={`${WSTAT_VALUE} mt-2`}>
              {signalWarehouseHealth ? totalSignalFactRows.toLocaleString() : "-"}
            </p>
          </div>
          <div className={INSET}>
            <p className={MICRO_LABEL}>Backfill coverage</p>
            <p className={`${WSTAT_VALUE} mt-2`}>
              {signalWarehouseHealth
                ? `${signalWarehouseHealth.backfill_coverage_pct.toFixed(2)}%`
                : "-"}
            </p>
          </div>
          <div className={INSET}>
            <p className={MICRO_LABEL}>Last ingested</p>
            <p className="mt-2 text-xs font-semibold text-(--t-1)">
              {signalWarehouseHealth?.last_ingested_at ? (
                <ClientSafeDate date={signalWarehouseHealth.last_ingested_at} format="datetime" />
              ) : (
                "No signal ingestion yet"
              )}
            </p>
          </div>
          <div className={INSET}>
            <p className={MICRO_LABEL}>Snapshots / benchmarks</p>
            <p className="mt-2 text-xs font-semibold tabular-nums text-(--t-1)">
              {signalWarehouseHealth
                ? `${signalWarehouseHealth.total_signal_audit_snapshots.toLocaleString()} / ${signalWarehouseHealth.total_benchmark_cohort_aggregates.toLocaleString()}`
                : "-"}
            </p>
            <p className={`${MONO_META} mt-1`}>
              <span className={MICRO_LABEL}>Proprietary scores</span>{" "}
              {signalWarehouseHealth
                ? signalWarehouseHealth.total_proprietary_scores.toLocaleString()
                : "-"}
            </p>
          </div>
        </div>

        {signalBackfillResult ? (
          <Alert className="mt-5">
            <AlertDescription>
              <span className={`${MONO_META} text-(--t-1)`}>
                Backfill job {signalBackfillResult.status.replace(/_/g, " ")} ·{" "}
                {signalBackfillResult.job_id}
              </span>
              <br />
              Audits: {signalBackfillResult.audits_processed.toLocaleString()} · Batches:{" "}
              {signalBackfillResult.batches_processed.toLocaleString()} · Rows:{" "}
              {signalBackfillResult.rows_inserted.toLocaleString()}
              {signalBackfillResult.errors.length > 0 ? (
                <span className="text-(--warn)">
                  {" "}
                  · Errors: {signalBackfillResult.errors.length}
                </span>
              ) : null}
            </AlertDescription>
          </Alert>
        ) : null}
      </section>

      {/* Cache lookup */}
      <section className={WSEC}>
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h3 className={`${SEC_TITLE} mb-1.5`}>
              <Search size={14} className="text-(--link)" /> Cache lookup
            </h3>
            <p className="text-xs text-(--t-3)">
              Look up cached validation headers and metadata for specific URLs or audit IDs.
            </p>
          </div>
          <Database size={24} className="text-(--line)" />
        </div>

        {cacheLookupError ? (
          <Alert variant="destructive" className="mb-5">
            <AlertTriangle size={16} />
            <AlertDescription>{cacheLookupError}</AlertDescription>
          </Alert>
        ) : null}

        <div className="grid grid-cols-1 items-end gap-4 lg:grid-cols-[1.5fr_1fr_1fr_1fr_auto]">
          <div className="space-y-1.5">
            <label className={MICRO_LABEL}>URL</label>
            <input
              type="text"
              value={cacheLookupUrl}
              onChange={(event) => setCacheLookupUrl(event.target.value)}
              placeholder="https://example.com/..."
              className={WINPUT}
              disabled={cacheLookupDisabled}
            />
          </div>
          <div className="space-y-1.5">
            <label className={MICRO_LABEL}>AI provider</label>
            <NativeSelect
              variant="auth"
              value={cacheLookupProvider}
              onChange={(event) => setCacheLookupProvider(event.target.value)}
              className="h-9 w-full text-[12.5px]"
              disabled={cacheLookupDisabled}
            >
              <option value="google">Google</option>
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
            </NativeSelect>
          </div>
          <div className="space-y-1.5">
            <label className={MICRO_LABEL}>Tier</label>
            <NativeSelect
              variant="auth"
              value={cacheLookupTier}
              onChange={(event) => setCacheLookupTier(event.target.value)}
              className="h-9 w-full text-[12.5px]"
              disabled={cacheLookupDisabled}
            >
              <option value="standard">Standard</option>
              <option value="deep">Deep Reasoning</option>
            </NativeSelect>
          </div>
          <div className="space-y-1.5">
            <label className={MICRO_LABEL}>Audit ID</label>
            <input
              type="text"
              value={cacheLookupAuditId}
              onChange={(event) => setCacheLookupAuditId(event.target.value)}
              placeholder="000"
              className={`${WINPUT} tabular-nums`}
              disabled={cacheLookupDisabled}
            />
          </div>
          <Button onClick={handleCacheLookup} disabled={cacheLookupDisabled}>
            {isCacheLookupLoading ? (
              <RefreshCw size={14} className="animate-spin" />
            ) : (
              <Search size={14} />
            )}
            Search
          </Button>
        </div>

        {cacheLookupResult && (
          <div className="mt-6 grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
            {[
              {
                label: "Cached at",
                value: cacheLookupResult.cached_at ? (
                  <ClientSafeDate date={cacheLookupResult.cached_at} />
                ) : (
                  "Not cached"
                ),
                icon: <Clock size={12} className="text-(--purple)" />,
              },
              {
                label: "Tier",
                value: cacheLookupResult.tier,
                icon: <Zap size={12} className="text-(--warn)" />,
              },
              {
                label: "Content hash",
                value: cacheLookupResult.content_hash ?? "N/A",
                icon: <Terminal size={12} className="text-(--t-2)" />,
                mono: true,
              },
              {
                label: "ETag",
                value: cacheLookupResult.etag ?? "N/A",
                icon: <Terminal size={12} className="text-(--t-2)" />,
                mono: true,
              },
              {
                label: "Last modified",
                value: cacheLookupResult.last_modified ?? "N/A",
                icon: <Clock size={12} className="text-(--t-2)" />,
                mono: true,
              },
              {
                label: "Source",
                value: cacheLookupResult.audit_id
                  ? `Audit #${cacheLookupResult.audit_id}`
                  : `${cacheLookupResult.provider}`,
                icon: <Globe size={12} className="text-(--link)" />,
              },
            ].map((item, idx) => (
              <div key={idx} className={INSET}>
                <div className="mb-2 flex items-center gap-2">
                  {item.icon}
                  <p className={MICRO_LABEL}>{item.label}</p>
                </div>
                <div
                  className={`truncate text-xs font-semibold text-(--t-1) ${item.mono ? "font-(family-name:--mono) text-[11px]" : ""}`}
                >
                  {item.value}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Recent admin actions */}
      {recentActions.length > 0 && (
        <section className={WSEC}>
          <div className="mb-5 flex items-center justify-between">
            <h3 className={SEC_TITLE}>
              <ScrollText size={14} className="text-(--purple)" /> Recent admin actions
            </h3>
            <Link href="/admin/audit-trail" className={SLINK}>
              View all <Eye size={12} />
            </Link>
          </div>
          <div className="space-y-1">
            {recentActions.map((entry) => (
              <div
                key={entry.id}
                className="group flex items-center gap-4 rounded-(--r-sm) px-4 py-3 transition-colors hover:bg-(--paper)"
              >
                <div className="shrink-0">
                  <div className="flex h-8 w-8 items-center justify-center rounded-(--r-sm) bg-(--purple-s) text-(--purple)">
                    <Activity size={14} />
                  </div>
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-semibold text-(--t-1)">
                    {entry.action.replace(/_/g, " ")}
                    {entry.target_id && (
                      <span className="ml-2 font-(family-name:--mono) text-(--t-3)">
                        #{entry.target_id}
                      </span>
                    )}
                  </p>
                  <p className={`${MONO_META} mt-0.5`}>
                    {entry.admin_email ?? "System"}
                    {entry.target_type && <> · {entry.target_type}</>}
                  </p>
                </div>
                <div className="shrink-0 text-right">
                  <span className="text-[11px] text-(--t-3)">
                    <ClientSafeDate date={entry.created_at} />
                  </span>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </>
  );
}
