"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  Activity,
  Clock,
  Zap,
  AlertCircle,
  Server,
  CheckCircle2,
  GitBranch,
  Shield,
  Waypoints,
} from "lucide-react";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { AdminInlineError } from "@/components/admin/AdminInlineError";
import { AdminCardSkeleton, AdminTableSkeleton } from "@/components/admin/AdminTableSkeleton";
import { TIER_SHORT } from "@/constants/tiers";
import { requestJson } from "@/services/http";
import {
  CHART_AXIS_TICK,
  CHART_GRID_STROKE,
  CHART_TOOLTIP_STYLE,
} from "@/components/ui/chartTokens";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
} from "recharts";

/* ── Types ──────────────────────────────────────────────────────── */

type MetricsSnapshot = {
  id: number;
  snapshot_at: string;
  requests_total: number;
  requests_2xx: number;
  requests_4xx: number;
  requests_5xx: number;
  latency_avg_ms: number;
  audit_jobs_completed: number;
  audit_jobs_failed: number;
  slow_endpoints: Record<string, number>;
};

type DualTrackGroundingSnapshot = {
  description: string | null;
  mode: "canonical_deep_judgment";
  effective_scope: "deep_judgment_only";
  source: "canonical";
  metrics: {
    claims_observed: number;
    reason_codes_observed: number;
    fallbacks_observed: number;
    claim_dispositions: Record<string, Record<string, number>>;
    reason_codes: Record<string, Record<string, number>>;
    fallback_reasons: Record<string, number>;
    top_reason_codes: Array<{
      track: string;
      reason_code: string;
      count: number;
    }>;
  };
};

type PromptQualityGateSnapshot = {
  schema_version: string;
  window_days: number;
  audits_checked: number;
  audits_failed: number;
  failure_rate: number;
  thresholds: Record<string, number>;
  top_violations: Array<{
    code: string;
    count: number;
  }>;
  tier_summary: Record<
    string,
    {
      audits_checked: number;
      audits_failed: number;
      violation_count: number;
      failure_rate: number;
    }
  >;
  recent_failures: Array<{
    audit_id: number;
    created_at: string | null;
    requested_tier: string;
    pipeline_type: string;
    violation_codes: string[];
  }>;
  comparison?: {
    previous_window: {
      window_days: number;
      audits_checked: number;
      audits_failed: number;
      failure_rate: number;
    };
    deltas: {
      audits_checked: number;
      audits_failed: number;
      failure_rate: number;
    };
  };
};

type PromptQualityCalibrationSnapshot = {
  schema_version: string;
  summary: {
    audits_considered: number;
    audits_with_quality_gate: number;
    audits_failed: number;
    failure_rate: number;
    audits_with_traces: number;
    calibration_ready_audits: number;
    calibration_ready_failures: number;
  };
  audits: Array<{
    audit_id: number;
    requested_tier: string;
    pipeline_type: string;
    quality_gate_passed: boolean | null;
    trace_count: number;
    calibration_ready: boolean;
    missing_artifacts: string[];
    suggested_prompt_files: string[];
    violation_codes: string[];
  }>;
};

const DUAL_TRACK_MODE_LABELS: Record<DualTrackGroundingSnapshot["mode"], string> = {
  canonical_deep_judgment: "Canonical Deep Judgment",
};
const PROMPT_TIER_FILTERS = [
  { value: "all", label: "All tiers" },
  { value: "fast", label: TIER_SHORT.fast },
  { value: "smart", label: TIER_SHORT.smart },
  { value: "deep_judgment", label: TIER_SHORT.deep_judgment },
] as const;

const DAY_OPTIONS = [1, 7, 30] as const;

/* ── Design tokens ──────────────────────────────────────────────── */

const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const MONO_META = MICRO_LABEL.replace("uppercase ", "");
const WSEC = "rounded-(--r) border border-(--line) bg-(--panel) px-[22px] py-[18px]";
const SEC_TITLE =
  "m-0 mb-4 flex items-center gap-2 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)";
const INSET = "rounded-(--r-md) border border-(--line) bg-(--paper) p-4";
const CHIPPED =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";
const SEG_BUTTON =
  "rounded-(--r-sm) px-2.5 py-1 font-(family-name:--mono) text-[11px] tracking-[0.04em] transition-colors";

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
      <p className={`${MONO_META} mb-2`}>
        {new Date(label as string).toLocaleString([], {
          dateStyle: "short",
          timeStyle: "short",
        })}
      </p>
      {payload.map((e, i) => (
        <p
          key={i}
          className="mb-1 flex items-center gap-2 text-xs font-semibold"
          style={{ color: e.color }}
        >
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: e.color }} />
          {e.name}:{" "}
          {typeof e.value === "number" && !Number.isInteger(e.value) ? e.value.toFixed(2) : e.value}
        </p>
      ))}
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
    <div className={WSEC + " flex items-center gap-4 !p-4"}>
      <div
        className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-(--r-md) bg-(--paper) ${color}`}
      >
        {icon}
      </div>
      <div className="min-w-0">
        <p className={MICRO_LABEL}>{label}</p>
        <p className="font-(family-name:--disp) text-xl font-bold text-(--t-1)">{value}</p>
      </div>
    </div>
  );
}

/* ── Main page ──────────────────────────────────────────────────── */

export default function AdminObservabilityPage() {
  const { isLoading: isGuardLoading } = useAdminAccess();
  const { setHeader } = useWorkspacePageHeader();

  const [metrics, setMetrics] = useState<MetricsSnapshot[]>([]);
  const [slowEndpoints, setSlowEndpoints] = useState<Record<string, number>>({});
  const [uptime, setUptime] = useState<{
    uptime_percentage: number;
    total_downtime_minutes: number;
  } | null>(null);
  const [dualTrackSnapshot, setDualTrackSnapshot] = useState<DualTrackGroundingSnapshot | null>(
    null
  );
  const [promptQualityGate, setPromptQualityGate] = useState<PromptQualityGateSnapshot | null>(
    null
  );
  const [promptQualityCalibration, setPromptQualityCalibration] =
    useState<PromptQualityCalibrationSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [days, setDays] = useState(7);
  const [selectedPromptTier, setSelectedPromptTier] =
    useState<(typeof PROMPT_TIER_FILTERS)[number]["value"]>("all");

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const promptFilterQuery = new URLSearchParams({ days: String(days) });
      if (selectedPromptTier !== "all") {
        promptFilterQuery.set("tier", selectedPromptTier);
      }
      const [metricsData, slowData, uptimeData] = await Promise.all([
        requestJson<MetricsSnapshot[]>({
          endpoint: `/api/v1/admin/observability/metrics?days=${days}`,
          method: "GET",
          errorMessage: "Failed to load metrics data.",
        }),
        requestJson<Record<string, number>>({
          endpoint: `/api/v1/admin/observability/slow-endpoints?days=${days}`,
          method: "GET",
          errorMessage: "Failed to load slow endpoints.",
        }),
        requestJson<{ uptime_percentage: number; total_downtime_minutes: number }>({
          endpoint: `/api/v1/admin/observability/uptime?days=${days}`,
          method: "GET",
          errorMessage: "Failed to load uptime data.",
        }),
      ]);

      setMetrics(metricsData);
      setSlowEndpoints(slowData);
      setUptime(uptimeData);

      // Non-critical panels, load gracefully
      try {
        const dtData = await requestJson<DualTrackGroundingSnapshot>({
          endpoint: `/api/v1/admin/observability/dual-track-grounding`,
          method: "GET",
          errorMessage: "Failed to load dual-track data.",
        });
        setDualTrackSnapshot(dtData);
      } catch {
        setDualTrackSnapshot(null);
      }

      try {
        const qgData = await requestJson<PromptQualityGateSnapshot>({
          endpoint: `/api/v1/admin/observability/prompt-quality-gate?${promptFilterQuery.toString()}`,
          method: "GET",
          errorMessage: "Failed to load quality gate data.",
        });
        setPromptQualityGate(qgData);
      } catch {
        setPromptQualityGate(null);
      }

      try {
        const calData = await requestJson<PromptQualityCalibrationSnapshot>({
          endpoint: `/api/v1/admin/observability/prompt-quality-calibration?${promptFilterQuery.toString()}`,
          method: "GET",
          errorMessage: "Failed to load calibration data.",
        });
        setPromptQualityCalibration(calData);
      } catch {
        setPromptQualityCalibration(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load observability dashboard.");
    } finally {
      setLoading(false);
    }
  }, [days, selectedPromptTier]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  /* Page-scoped `.top` action: the day-window segmented control. */
  useEffect(() => {
    setHeader({
      actions: (
        <div
          role="group"
          aria-label="Metrics window"
          className="hidden items-center gap-0.5 rounded-(--r-md) border border-(--line) bg-(--paper) p-0.5 sm:flex"
        >
          {DAY_OPTIONS.map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setDays(d)}
              className={`${SEG_BUTTON} ${
                days === d
                  ? "bg-(--panel) text-(--t-1) shadow-sm"
                  : "text-(--t-3) hover:text-(--t-1)"
              }`}
            >
              {d}d
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
        <DashboardPageIntro icon={Activity} title="System observability" />
        <AdminCardSkeleton cards={3} />
        <AdminTableSkeleton rows={5} columns={2} />
      </>
    );
  }

  if (error && metrics.length === 0) {
    return <AdminInlineError message={error} onRetry={loadData} />;
  }

  // Chart Data Preparation - Calculating deltas for graphing active throughput instead of cumulative
  const chartData = metrics
    .map((m, i, arr) => {
      if (i === 0) return { ...m, req_rate: 0, err_rate: 0, jobs_rate: 0 };
      const prev = arr[i - 1];
      const reqDelta = m.requests_total - prev.requests_total;
      const errDelta = m.requests_5xx - prev.requests_5xx;
      const jobsDelta = m.audit_jobs_completed - prev.audit_jobs_completed;

      return {
        ...m,
        req_rate: Math.max(0, reqDelta),
        err_rate: Math.max(0, errDelta),
        jobs_rate: Math.max(0, jobsDelta),
      };
    })
    .slice(1); // Remove first element which has 0 deltas

  const latest = metrics[metrics.length - 1];
  const totalReqsPeriod =
    latest && metrics[0] ? latest.requests_total - metrics[0].requests_total : 0;
  const avgLatency = latest ? latest.latency_avg_ms : 0;
  const dualTrackSourceLabel =
    dualTrackSnapshot?.source === "canonical" ? "Canonical runtime" : "Unknown";
  const dualTrackModeLabel = dualTrackSnapshot
    ? DUAL_TRACK_MODE_LABELS[dualTrackSnapshot.mode]
    : null;
  const promptQualityFailureRate = promptQualityGate
    ? `${Math.round(promptQualityGate.failure_rate * 100)}%`
    : "0%";
  const promptQualityPreviousFailureRate = promptQualityGate?.comparison
    ? `${Math.round(promptQualityGate.comparison.previous_window.failure_rate * 100)}%`
    : "0%";
  const promptQualityFailureRateDelta = promptQualityGate?.comparison?.deltas.failure_rate ?? 0;
  const promptQualityTrendTone =
    promptQualityFailureRateDelta > 0
      ? "text-(--warn)"
      : promptQualityFailureRateDelta < 0
        ? "text-(--good)"
        : "text-(--t-2)";
  const promptQualityTrendLabel = `${
    promptQualityFailureRateDelta > 0 ? "+" : ""
  }${Math.round(promptQualityFailureRateDelta * 100)} pts`;
  const calibrationReadyFailures = promptQualityCalibration
    ? promptQualityCalibration.audits.filter(
        (audit) => audit.calibration_ready && audit.quality_gate_passed === false
      )
    : [];
  const calibrationMissingArtifactsCount = promptQualityCalibration
    ? promptQualityCalibration.audits.filter((audit) => audit.missing_artifacts.length > 0).length
    : 0;

  return (
    <>
      <DashboardPageIntro icon={Activity} title="System observability">
        Historical performance charts, error rates, uptime tracking, and endpoint latency
        monitoring.
      </DashboardPageIntro>

      {/* Mobile duplicate of the `.top` metrics-window control (hidden at sm+). */}
      <div
        role="group"
        aria-label="Metrics window"
        className="flex items-center gap-0.5 self-start rounded-(--r-md) border border-(--line) bg-(--paper) p-0.5 sm:hidden"
      >
        {DAY_OPTIONS.map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => setDays(d)}
            className={`${SEG_BUTTON} ${
              days === d ? "bg-(--panel) text-(--t-1) shadow-sm" : "text-(--t-3) hover:text-(--t-1)"
            }`}
          >
            {d}d
          </button>
        ))}
      </div>

      {error && <AdminInlineError message={error} onRetry={loadData} />}

      {/* KPIs */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <StatTile
          label={`Uptime (${days}d)`}
          value={`${uptime?.uptime_percentage ?? 100}%`}
          icon={<CheckCircle2 size={24} />}
          color={(uptime?.uptime_percentage ?? 100) > 99.9 ? "text-(--good)" : "text-(--warn)"}
        />
        <StatTile
          label="Period requests"
          value={totalReqsPeriod.toLocaleString()}
          icon={<Server size={24} />}
        />
        <StatTile
          label="Avg latency"
          value={`${avgLatency.toFixed(1)} ms`}
          icon={<Zap size={24} />}
          color={avgLatency > 500 ? "text-(--warn)" : "text-(--good)"}
        />
      </div>

      {dualTrackSnapshot ? (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <section className={WSEC}>
            <h2 className={SEC_TITLE}>
              <GitBranch size={14} className="text-(--purple)" /> Dual-track grounding runtime
            </h2>
            <div className="grid gap-4 md:grid-cols-2">
              <div className={INSET}>
                <p className={MICRO_LABEL}>Execution scope</p>
                <p className="mt-2 break-all font-(family-name:--mono) text-sm font-semibold text-(--t-1)">
                  {dualTrackSnapshot.effective_scope}
                </p>
                <p className="mt-2 text-xs text-(--t-2)">
                  {dualTrackSnapshot.description ??
                    "Dual-track grounding is a canonical deep_judgment runtime."}
                </p>
              </div>
              <div className={INSET}>
                <p className={MICRO_LABEL}>Effective mode</p>
                <p className="mt-2 text-lg font-semibold text-(--t-1)">{dualTrackModeLabel}</p>
                <p className="mt-2 text-xs text-(--t-2)">
                  Source: {dualTrackSourceLabel}. No rollout gating remains.
                </p>
              </div>
              <div className={INSET}>
                <p className={MICRO_LABEL}>Authoritative path</p>
                <p className="mt-2 text-sm font-semibold text-(--t-1)">
                  Single-track remains client-safe
                </p>
                <p className="mt-2 text-xs text-(--t-2)">
                  Track B evidence is evaluated in shadow for `deep_judgment`, then recorded in
                  metadata.
                </p>
              </div>
              <div className={INSET}>
                <p className={MICRO_LABEL}>Transition status</p>
                <p className="mt-2 text-sm font-semibold text-(--t-1)">
                  Feature-flag cleanup complete
                </p>
                <p className="mt-2 text-xs text-(--t-2)">
                  This panel now reports runtime counters only, not rollout state.
                </p>
              </div>
            </div>
          </section>

          <section className={WSEC}>
            <h2 className={SEC_TITLE}>
              <Shield size={14} className="text-(--warn)" /> Dual-track shadow counters
            </h2>
            <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3">
              <div className={INSET}>
                <p className={MICRO_LABEL}>Claims observed</p>
                <p className="mt-1 font-(family-name:--disp) text-lg font-bold text-(--t-1)">
                  {dualTrackSnapshot.metrics.claims_observed.toLocaleString()}
                </p>
              </div>
              <div className={INSET}>
                <p className={MICRO_LABEL}>Reason codes</p>
                <p className="mt-1 font-(family-name:--disp) text-lg font-bold text-(--t-1)">
                  {dualTrackSnapshot.metrics.reason_codes_observed.toLocaleString()}
                </p>
              </div>
              <div className={INSET}>
                <p className={MICRO_LABEL}>Fallback events</p>
                <p
                  className={`mt-1 font-(family-name:--disp) text-lg font-bold ${
                    dualTrackSnapshot.metrics.fallbacks_observed > 0
                      ? "text-(--bad)"
                      : "text-(--good)"
                  }`}
                >
                  {dualTrackSnapshot.metrics.fallbacks_observed.toLocaleString()}
                </p>
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className={INSET}>
                <p className={`${MICRO_LABEL} mb-3`}>Top reason codes</p>
                {(dualTrackSnapshot.metrics.top_reason_codes ?? []).length > 0 ? (
                  <div className="space-y-2">
                    {dualTrackSnapshot.metrics.top_reason_codes.map((entry) => (
                      <div
                        key={`${entry.track}:${entry.reason_code}`}
                        className="rounded-(--r-sm) border border-(--line) bg-(--panel) px-3 py-2"
                      >
                        <p className="text-xs font-semibold text-(--t-1)">{entry.reason_code}</p>
                        <p className={`mt-1 ${MONO_META} text-[10px]`}>
                          {entry.track} · {entry.count.toLocaleString()} events
                        </p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-(--t-3)">
                    No shadow reason codes recorded in this process yet.
                  </p>
                )}
              </div>

              <div className={INSET}>
                <p className={`${MICRO_LABEL} mb-3`}>Fallback reasons</p>
                {Object.entries(dualTrackSnapshot.metrics.fallback_reasons ?? {}).length > 0 ? (
                  <div className="space-y-2">
                    {Object.entries(dualTrackSnapshot.metrics.fallback_reasons).map(
                      ([reason, count]) => (
                        <div
                          key={reason}
                          className="flex items-center justify-between rounded-(--r-sm) border border-(--line) bg-(--panel) px-3 py-2"
                        >
                          <span className="text-xs font-semibold text-(--t-1)">{reason}</span>
                          <span className={`${CHIPPED} text-(--bad) bg-(--bad-s)`}>
                            {count.toLocaleString()}
                          </span>
                        </div>
                      )
                    )}
                  </div>
                ) : (
                  <p className="text-xs text-(--t-3)">
                    No fallback reasons recorded in this process.
                  </p>
                )}
              </div>
            </div>
          </section>
        </div>
      ) : null}

      {promptQualityGate ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <span className={MICRO_LABEL}>Prompt tier filter</span>
            <div className="flex items-center gap-0.5 rounded-(--r-md) border border-(--line) bg-(--paper) p-0.5">
              {PROMPT_TIER_FILTERS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setSelectedPromptTier(option.value)}
                  className={`${SEG_BUTTON} ${
                    selectedPromptTier === option.value
                      ? "bg-(--panel) text-(--t-1) shadow-sm"
                      : "text-(--t-3) hover:text-(--t-1)"
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <section className={WSEC}>
              <h2 className={SEC_TITLE}>
                <Shield size={14} className="text-(--good)" /> Orchestra prompt quality gate
              </h2>
              <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3">
                <div className={INSET}>
                  <p className={MICRO_LABEL}>Audits checked</p>
                  <p className="mt-1 font-(family-name:--disp) text-lg font-bold text-(--t-1)">
                    {promptQualityGate.audits_checked.toLocaleString()}
                  </p>
                </div>
                <div className={INSET}>
                  <p className={MICRO_LABEL}>Audits failed</p>
                  <p
                    className={`mt-1 font-(family-name:--disp) text-lg font-bold ${
                      promptQualityGate.audits_failed > 0 ? "text-(--warn)" : "text-(--good)"
                    }`}
                  >
                    {promptQualityGate.audits_failed.toLocaleString()}
                  </p>
                </div>
                <div className={INSET}>
                  <p className={MICRO_LABEL}>Failure rate</p>
                  <p
                    className={`mt-1 font-(family-name:--disp) text-lg font-bold ${
                      promptQualityGate.failure_rate > 0 ? "text-(--warn)" : "text-(--good)"
                    }`}
                  >
                    {promptQualityFailureRate}
                  </p>
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className={INSET}>
                  <p className={MICRO_LABEL}>Threshold set</p>
                  <div className="mt-3 space-y-2">
                    {Object.entries(promptQualityGate.thresholds).map(([key, value]) => (
                      <div
                        key={key}
                        className="flex items-center justify-between rounded-(--r-sm) border border-(--line) bg-(--panel) px-3 py-2"
                      >
                        <span className="text-xs font-semibold text-(--t-1)">{key}</span>
                        <span className={`${CHIPPED} text-(--purple) bg-(--purple-s)`}>
                          {value}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className={INSET}>
                  <p className={`${MICRO_LABEL} mb-3`}>Top violations</p>
                  {promptQualityGate.top_violations.length > 0 ? (
                    <div className="space-y-2">
                      {promptQualityGate.top_violations.map((entry) => (
                        <div
                          key={entry.code}
                          className="flex items-center justify-between rounded-(--r-sm) border border-(--line) bg-(--panel) px-3 py-2"
                        >
                          <span className="text-xs font-semibold text-(--t-1)">{entry.code}</span>
                          <span className={`${CHIPPED} text-(--warn) bg-(--warn-s)`}>
                            {entry.count.toLocaleString()}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-(--t-3)">
                      No quality-gate violations were recorded in this window.
                    </p>
                  )}
                </div>
              </div>

              {promptQualityGate.comparison ? (
                <div className={`${INSET} mt-4`}>
                  <p className={MICRO_LABEL}>Window trend</p>
                  <p className="mt-2 text-xs text-(--t-2)">
                    Current {days}-day failure rate: {promptQualityFailureRate} vs previous window:{" "}
                    {promptQualityPreviousFailureRate}
                  </p>
                  <p className={`mt-2 ${MONO_META} ${promptQualityTrendTone}`}>
                    Failure rate delta: {promptQualityTrendLabel}
                  </p>
                </div>
              ) : null}
            </section>

            <section className={WSEC}>
              <h2 className={SEC_TITLE}>
                <GitBranch size={14} className="text-(--warn)" /> Recent failing audits
              </h2>
              <div className="mb-4 grid gap-4 md:grid-cols-2">
                {Object.entries(promptQualityGate.tier_summary).map(([tier, summary]) => (
                  <div key={tier} className={INSET}>
                    <p className={MONO_META}>{tier}</p>
                    <p className="mt-2 text-lg font-semibold text-(--t-1)">
                      {summary.audits_failed}/{summary.audits_checked} failed
                    </p>
                    <p className="mt-2 text-xs text-(--t-2)">
                      Violation count: {summary.violation_count.toLocaleString()} · Failure rate:{" "}
                      {Math.round(summary.failure_rate * 100)}%
                    </p>
                  </div>
                ))}
              </div>

              {promptQualityGate.recent_failures.length > 0 ? (
                <div className="space-y-2">
                  {promptQualityGate.recent_failures.map((entry) => (
                    <div
                      key={`${entry.audit_id}-${entry.created_at}`}
                      className="rounded-(--r-sm) border border-(--line) bg-(--paper) px-3 py-3"
                    >
                      <p className="text-xs font-semibold text-(--t-1)">
                        Audit #{entry.audit_id} · {entry.requested_tier} · {entry.pipeline_type}
                      </p>
                      <p className={`mt-1 ${MONO_META} text-[10px]`}>
                        {entry.created_at
                          ? new Date(entry.created_at).toLocaleString()
                          : "Unknown capture time"}
                      </p>
                      <p className="mt-2 text-xs text-(--t-2)">
                        {entry.violation_codes.join(", ")}
                      </p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-(--t-3)">
                  No failed Orchestra prompt-quality checks were recorded in this window.
                </p>
              )}
            </section>
          </div>
        </>
      ) : null}

      {promptQualityCalibration ? (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <section className={WSEC}>
            <h2 className={SEC_TITLE}>
              <Waypoints size={14} className="text-(--purple)" /> Prompt calibration workflow
            </h2>
            <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3">
              <div className={INSET}>
                <p className={MICRO_LABEL}>Trace coverage</p>
                <p className="mt-1 font-(family-name:--disp) text-lg font-bold text-(--t-1)">
                  {promptQualityCalibration.summary.audits_with_traces}/
                  {promptQualityCalibration.summary.audits_considered}
                </p>
              </div>
              <div className={INSET}>
                <p className={MICRO_LABEL}>Calibration ready</p>
                <p className="mt-1 font-(family-name:--disp) text-lg font-bold text-(--good)">
                  {promptQualityCalibration.summary.calibration_ready_audits.toLocaleString()}
                </p>
              </div>
              <div className={INSET}>
                <p className={MICRO_LABEL}>Ready failures</p>
                <p
                  className={`mt-1 font-(family-name:--disp) text-lg font-bold ${
                    promptQualityCalibration.summary.calibration_ready_failures > 0
                      ? "text-(--warn)"
                      : "text-(--good)"
                  }`}
                >
                  {promptQualityCalibration.summary.calibration_ready_failures.toLocaleString()}
                </p>
              </div>
            </div>

            <div className={INSET}>
              <p className={MICRO_LABEL}>Human review still required</p>
              <p className="mt-2 text-xs leading-relaxed text-(--t-2)">
                The automated gate is only a pre-filter. Prompt specificity, critic accuracy, false
                dedup checks, override quality, and cross-tier comparisons still need operator
                review against the stored debate traces.
              </p>
              <p className={`mt-3 ${MONO_META} text-[10px]`}>
                Audits missing traces or gate data in this window:{" "}
                {calibrationMissingArtifactsCount.toLocaleString()}
              </p>
            </div>
          </section>

          <section className={WSEC}>
            <h2 className={SEC_TITLE}>
              <Shield size={14} className="text-(--warn)" /> Calibration-ready failures
            </h2>
            {calibrationReadyFailures.length > 0 ? (
              <div className="space-y-3">
                {calibrationReadyFailures.map((entry) => (
                  <div
                    key={entry.audit_id}
                    className="rounded-(--r-sm) border border-(--line) bg-(--paper) px-3 py-3"
                  >
                    <p className="text-xs font-semibold text-(--t-1)">
                      Audit #{entry.audit_id} · {entry.requested_tier} · {entry.pipeline_type}
                    </p>
                    <p className={`mt-2 ${MICRO_LABEL} text-[10px]`}>Violation codes</p>
                    <p className="mt-1 text-xs text-(--t-2)">{entry.violation_codes.join(", ")}</p>
                    <p className={`mt-2 ${MICRO_LABEL} text-[10px]`}>Suggested prompt files</p>
                    <p className="mt-1 break-all font-(family-name:--mono) text-xs text-(--t-2)">
                      {entry.suggested_prompt_files.join(", ")}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-(--t-3)">
                No audits in this window are both trace-complete and failing the quality gate.
              </p>
            )}
          </section>
        </div>
      ) : null}

      {/* Charts */}
      {chartData.length > 0 ? (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <section className={WSEC}>
            <h2 className={SEC_TITLE}>
              <Activity size={14} className="text-(--purple)" /> Throughput and errors
            </h2>
            <div className="h-[250px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorReq" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="var(--purple)" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="var(--purple)" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="colorErr" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="var(--bad)" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="var(--bad)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke={CHART_GRID_STROKE}
                    vertical={false}
                  />
                  <XAxis
                    dataKey="snapshot_at"
                    tickFormatter={(t) =>
                      new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                    }
                    tick={CHART_AXIS_TICK}
                  />
                  <YAxis tick={CHART_AXIS_TICK} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTooltip />} />
                  <Area
                    type="monotone"
                    dataKey="req_rate"
                    name="Requests"
                    stroke="var(--purple)"
                    strokeWidth={2}
                    fillOpacity={1}
                    fill="url(#colorReq)"
                  />
                  <Area
                    type="monotone"
                    dataKey="err_rate"
                    name="Errors (5xx)"
                    stroke="var(--bad)"
                    strokeWidth={2}
                    fillOpacity={1}
                    fill="url(#colorErr)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className={WSEC}>
            <h2 className={SEC_TITLE}>
              <Clock size={14} className="text-(--purple)" /> Global latency (ms)
            </h2>
            <div className="h-[250px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke={CHART_GRID_STROKE}
                    vertical={false}
                  />
                  <XAxis
                    dataKey="snapshot_at"
                    tickFormatter={(t) =>
                      new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                    }
                    tick={CHART_AXIS_TICK}
                  />
                  <YAxis tick={CHART_AXIS_TICK} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTooltip />} />
                  <Line
                    type="monotone"
                    dataKey="latency_avg_ms"
                    name="Avg latency"
                    stroke="var(--good)"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 6 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </section>
        </div>
      ) : (
        <section className={`${WSEC} py-12 text-center`}>
          <Activity size={32} className="mx-auto mb-4 text-(--purple) opacity-50" />
          <p className="text-sm font-semibold text-(--t-1)">
            No metrics data available for this period
          </p>
          <p className="mt-2 text-xs text-(--t-3)">
            Wait for the cron job to collect the first snapshot.
          </p>
        </section>
      )}

      {/* Slow endpoints */}
      <section className="overflow-hidden rounded-(--r) border border-(--line) bg-(--panel)">
        <div className="border-b border-(--line) px-[22px] py-[14px]">
          <h2 className="m-0 flex items-center gap-2 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)">
            <AlertCircle size={14} className="text-(--warn)" /> Slow endpoints detection (&gt;500ms)
          </h2>
        </div>
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-(--line)">
              <th className={`p-4 ${MICRO_LABEL}`}>Endpoint</th>
              <th className={`p-4 text-right ${MICRO_LABEL}`}>Avg latency (ms)</th>
              <th className={`p-4 text-right ${MICRO_LABEL}`}>Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-(--line)">
            {Object.entries(slowEndpoints).map(([endpoint, latency]) => (
              <tr key={endpoint} className="transition-colors hover:bg-(--paper)">
                <td className="break-all p-4 font-(family-name:--mono) text-xs text-(--t-1)">
                  <span className="mr-2 font-semibold text-(--purple)">
                    {endpoint.split(" ")[0]}
                  </span>
                  {endpoint.split(" ").slice(1).join(" ")}
                </td>
                <td className="p-4 text-right font-(family-name:--mono) text-xs text-(--t-2)">
                  {latency.toLocaleString()} ms
                </td>
                <td className="p-4 text-right">
                  <span
                    className={`${CHIPPED} ${
                      latency > 1500
                        ? "text-(--bad) bg-(--bad-s)"
                        : latency > 1000
                          ? "text-(--warn) bg-(--warn-s)"
                          : "text-(--good) bg-(--good-s)"
                    }`}
                  >
                    {latency > 1500 ? "Critical" : latency > 1000 ? "Warning" : "Needs review"}
                  </span>
                </td>
              </tr>
            ))}
            {Object.keys(slowEndpoints).length === 0 && (
              <tr>
                <td colSpan={3} className={`p-8 text-center ${MONO_META}`}>
                  No slow endpoints detected in current snapshot
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </>
  );
}
