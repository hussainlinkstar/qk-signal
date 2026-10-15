"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Loader2, Minus } from "lucide-react";

import { useAuth } from "@/components/auth/custom-auth";
import GatedSection from "@/components/results/GatedSection";
import { CARD_SUBSECTION_SURFACE_CLASS } from "@/components/ui/cardStyleTokens";
import { cx } from "@/components/ui/utils";
import { formatDateTime } from "@/lib/dateFormat";
import { resolvePlanCapabilities } from "@/lib/planCapabilities";
import { getErrorStatus, getPlanLockContent } from "@/lib/planLocks";
import {
  fetchAdvisorPlanProgress,
  type PlanProgress,
  type PlanTrendPoint,
} from "@/services/planProgressService";

type PlanProgressViewProps = {
  projectId: string;
};

const SAMPLE_PREVIEW_TREND: ReadonlyArray<PlanTrendPoint> = [
  { created_at: "2026-01-04T09:00:00Z", total_actions: 14, high_impact: 6 },
  { created_at: "2026-02-04T09:00:00Z", total_actions: 11, high_impact: 4 },
  { created_at: "2026-03-04T09:00:00Z", total_actions: 8, high_impact: 2 },
];

/** A compact vertical-bar trend (no chart lib — scaled divs). */
function TrendBars({ trend }: { trend: ReadonlyArray<PlanTrendPoint> }) {
  const maxTotal = Math.max(1, ...trend.map((point) => point.total_actions));

  return (
    <div className="flex items-end gap-3" data-testid="plan-progress-trend">
      {trend.map((point, index) => {
        const totalPct = Math.round((point.total_actions / maxTotal) * 100);
        const highPct = Math.round((point.high_impact / maxTotal) * 100);
        const label = point.created_at ? formatDateTime(point.created_at) : `Audit ${index + 1}`;
        return (
          <div
            key={`${point.created_at ?? "snapshot"}-${index}`}
            className="flex flex-1 flex-col items-center gap-2"
          >
            <div
              className="relative flex h-28 w-full items-end justify-center rounded bg-(--surface-elevated)"
              role="img"
              aria-label={`${label}: ${point.total_actions} total actions, ${point.high_impact} high-impact`}
            >
              {/* Total actions bar */}
              <div
                className="absolute bottom-0 h-(--bh) w-2/3 rounded-t bg-(--purple) opacity-40"
                style={{ "--bh": `${Math.max(totalPct, 4)}%` } as React.CSSProperties}
              />
              {/* High-impact overlay */}
              <div
                className="absolute bottom-0 h-(--bh) w-2/3 rounded-t bg-(--purple)"
                style={
                  {
                    "--bh": `${Math.max(highPct, point.high_impact > 0 ? 4 : 0)}%`,
                  } as React.CSSProperties
                }
              />
            </div>
            <span className="text-[11px] font-medium text-(--foreground)">
              {point.total_actions}
            </span>
            <span className="text-[10px] text-(--text-muted)">{label}</span>
          </div>
        );
      })}
    </div>
  );
}

function PlanProgressPreview() {
  return (
    <div className={cx(CARD_SUBSECTION_SURFACE_CLASS, "space-y-4")}>
      <TrendBars trend={SAMPLE_PREVIEW_TREND} />
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: "Added", value: 2 },
          { label: "Resolved", value: 5 },
          { label: "Carried", value: 6 },
        ].map((item) => (
          <div
            key={item.label}
            className="rounded border-0 bg-(--surface-elevated) p-4 text-center shadow-(--shadow-inset)"
          >
            <p className="text-2xl font-semibold text-(--foreground)">{item.value}</p>
            <p className="text-[10px] uppercase tracking-[0.18em] text-(--text-muted)">
              {item.label}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

type DeltaChipTone = "down" | "up" | "flat";

function DeltaChip({ delta, noun }: { delta: number; noun: string }) {
  // For action counts, a decrease (▼) is the desirable direction, so colour
  // the reduction green and an increase amber. Honest, not over-claimed.
  let tone: DeltaChipTone = "flat";
  if (delta < 0) {
    tone = "down";
  } else if (delta > 0) {
    tone = "up";
  }

  const toneClass: Record<DeltaChipTone, string> = {
    down: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
    up: "border-amber-500/30 bg-amber-500/10 text-amber-300",
    flat: "border-(--border) bg-(--surface-subtle) text-(--text-muted)",
  };

  const magnitude = Math.abs(delta);
  const Icon = tone === "down" ? ArrowDown : tone === "up" ? ArrowUp : Minus;
  const phrase =
    tone === "down"
      ? `${magnitude} ${noun} resolved since last audit`
      : tone === "up"
        ? `${magnitude} ${noun} added since last audit`
        : `No change in ${noun} since last audit`;

  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium",
        toneClass[tone]
      )}
    >
      <Icon className="h-3 w-3" />
      {phrase}
    </span>
  );
}

/**
 * Read-only Executive view of how a project's Advisor plan evolves across audits
 * (R12 continuous-management value). Shows a compact trend (total + high-impact
 * actions over time) and the latest audit-over-audit delta. No auto-execution,
 * no mutations — purely derived from persisted Advisor-plan snapshots.
 */
export default function PlanProgressView({ projectId }: PlanProgressViewProps) {
  const { getToken, isLoading: authLoading, isSignedIn, user } = useAuth();

  const capabilities = resolvePlanCapabilities(user?.subscription_plan);
  // Fail-safe locked: unknown / unresolved plans resolve every premium
  // capability to `false`, so the section stays gated until the plan is known
  // to include done-for-you execution (Executive+).
  const planLocked = !capabilities.has_done_for_you_execution;

  const [apiLocked, setApiLocked] = useState(false);
  const [loading, setLoading] = useState(true);
  const [progress, setProgress] = useState<PlanProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isLocked = planLocked || apiLocked;

  const getAuthHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to view Advisor plan progress.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const loadProgress = useCallback(async () => {
    if (!projectId || authLoading) {
      return;
    }
    if (!isSignedIn || planLocked) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      const payload = await fetchAdvisorPlanProgress(projectId, headers);
      setProgress(payload);
      setApiLocked(false);
    } catch (loadError) {
      if (getErrorStatus(loadError) === 402) {
        setApiLocked(true);
      } else {
        setError(
          loadError instanceof Error ? loadError.message : "Unable to load Advisor plan progress."
        );
      }
    } finally {
      setLoading(false);
    }
  }, [authLoading, getAuthHeaders, isSignedIn, planLocked, projectId]);

  useEffect(() => {
    void loadProgress();
  }, [loadProgress]);

  const trend = useMemo(() => progress?.trend ?? [], [progress]);
  const hasTrend = trend.length >= 2;

  if (isLocked) {
    const lock = getPlanLockContent("doneForYouExecution");
    return (
      <GatedSection
        title="Plan Progress"
        teaser="See how your Advisor action plan evolves across audits: high-impact fixes resolved, new actions surfaced, and what's carried forward."
        requiredPlan="plan_executive"
        requiredPlanLabel={lock.requiredPlanLabel}
        blurredPreview={<PlanProgressPreview />}
      />
    );
  }

  const shellCls = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";

  if (authLoading || loading) {
    return (
      <section className={shellCls}>
        <div className="flex items-center gap-3 text-[13px] text-(--t-3)">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading plan progress...
        </div>
      </section>
    );
  }

  if (!isSignedIn) {
    return (
      <section className={shellCls}>
        <p className="m-0 text-[13px] text-(--t-3)">
          Sign in to review how this project&apos;s Advisor plan evolves across audits.
        </p>
      </section>
    );
  }

  const delta = progress?.latest_delta ?? null;

  return (
    <section className={shellCls} data-testid="plan-progress-view">
      {/* Approved `.wsec` head. */}
      <h3 className="m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
        Plan Progress
      </h3>
      <p className="mt-1 text-[12.5px] leading-[1.5] text-(--t-3)">
        Each audit captures a snapshot of your Advisor action plan, tracking open actions and the
        high-impact backlog over time. Read-only.
      </p>

      {error ? (
        <p className="mt-3 text-[12px] text-(--bad)" role="alert">
          {error}
        </p>
      ) : null}

      {!hasTrend ? (
        <div className="mt-4 rounded-[14px] border border-dashed border-[#D1D5DB] bg-[#F8FAFC] px-4 py-[26px] text-center text-[13px] text-(--t-3)">
          Not enough history yet.
        </div>
      ) : (
        <>
          <div className="mt-4 border-t border-t-(--line-2) pt-4">
            <div className="flex items-center justify-between">
              <div className="text-[13.5px] font-semibold">Open actions over time</div>
              <div className="flex items-center gap-3 text-[10px] uppercase tracking-[0.18em] text-(--t-3)">
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-sm bg-(--purple) opacity-40" /> Total
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-sm bg-(--purple)" /> High-impact
                </span>
              </div>
            </div>
            <div className="mt-3">
              <TrendBars trend={trend} />
            </div>
          </div>

          {delta ? (
            <div
              className="mt-4 border-t border-t-(--line-2) pt-4"
              data-testid="plan-progress-delta"
            >
              <div className="text-[13.5px] font-semibold">Since your last audit</div>
              <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
                <div className="rounded-[12px] border-0 bg-[#EEF1F6] px-[18px] py-4 text-center">
                  <p className="m-0 font-(family-name:--disp) text-[20px] font-extrabold tracking-[-0.02em] text-(--t-1)">
                    {delta.actions_added.length}
                  </p>
                  <p className="m-0 mt-1 font-mono text-[10px] uppercase tracking-[0.08em] text-(--t-3)">
                    New actions
                  </p>
                </div>
                <div className="rounded-[12px] border-0 bg-[#EEF1F6] px-[18px] py-4 text-center">
                  <p className="m-0 font-(family-name:--disp) text-[20px] font-extrabold tracking-[-0.02em] text-(--good)">
                    {delta.actions_resolved.length}
                  </p>
                  <p className="m-0 mt-1 font-mono text-[10px] uppercase tracking-[0.08em] text-(--t-3)">
                    Resolved
                  </p>
                </div>
                <div className="rounded-[12px] border-0 bg-[#EEF1F6] px-[18px] py-4 text-center">
                  <p className="m-0 font-(family-name:--disp) text-[20px] font-extrabold tracking-[-0.02em] text-(--t-1)">
                    {delta.actions_carried.length}
                  </p>
                  <p className="m-0 mt-1 font-mono text-[10px] uppercase tracking-[0.08em] text-(--t-3)">
                    Carried forward
                  </p>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <DeltaChip delta={delta.impact_delta.high_impact} noun="high-impact" />
                <DeltaChip delta={delta.impact_delta.total_actions} noun="total" />
              </div>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
