"use client";

import React from "react";
import { Activity, AlertTriangle, BarChart3, Lock, Loader2 } from "lucide-react";

import { GlassCard } from "@/components/ui/GlassComponents";
import type { BenchmarkPercentileResponse, ProprietaryScoreResponse } from "@/types/benchmark";
import { requiredPlanLabelForCapability } from "@/lib/planCapabilities";

const BENCHMARK_REQUIRED_PLAN_LABEL = requiredPlanLabelForCapability("entity_authority");

type BenchmarkPercentileBadgeProps = {
  loading: boolean;
  planLocked: boolean;
  error: string | null;
  benchmark: BenchmarkPercentileResponse | null;
  citationStability: ProprietaryScoreResponse | null;
  remediationImpact: ProprietaryScoreResponse | null;
};

const formatScore = (value: number | null | undefined): string => {
  if (typeof value !== "number") {
    return "N/A";
  }
  return `${Math.round(value)}`;
};

export default function BenchmarkPercentileBadge({
  loading,
  planLocked,
  error,
  benchmark,
  citationStability,
  remediationImpact,
}: BenchmarkPercentileBadgeProps) {
  if (loading) {
    return (
      <GlassCard className="p-5 border-(--line) bg-(--line-2)">
        <div className="flex items-center gap-2 text-xs font-black uppercase tracking-widest text-(--t-3)">
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
          Loading Benchmark Intelligence
        </div>
      </GlassCard>
    );
  }

  if (planLocked) {
    return (
      <GlassCard className="p-5 border-amber-400/30 bg-amber-500/10">
        <div className="flex items-start gap-3">
          <Lock className="mt-0.5 h-4 w-4 text-amber-300" />
          <div className="space-y-1">
            {/* SIGV2-1221: derived from `entity_authority`, the capability
                `benchmark_router` actually gates this on. */}
            <p className="text-xs font-black uppercase tracking-wider text-amber-100">
              {BENCHMARK_REQUIRED_PLAN_LABEL
                ? `Benchmark comparisons are available on ${BENCHMARK_REQUIRED_PLAN_LABEL}.`
                : "Benchmark comparisons are not available on this plan."}
            </p>
            <p className="text-xs text-amber-50/80">
              Upgrade to unlock cohort percentiles and proprietary impact signals.
            </p>
          </div>
        </div>
      </GlassCard>
    );
  }

  if (error) {
    return (
      <GlassCard className="p-5 border-rose-400/30 bg-rose-500/10">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 text-rose-200" />
          <div className="space-y-1">
            <p className="text-xs font-black uppercase tracking-wider text-rose-100">
              Benchmark intelligence is temporarily unavailable.
            </p>
            <p className="text-xs text-rose-100/90">{error}</p>
          </div>
        </div>
      </GlassCard>
    );
  }

  if (!benchmark || benchmark.status !== "ok" || benchmark.top_percent == null) {
    return (
      <GlassCard className="p-5 border-(--line) bg-(--line-2)">
        <div className="flex items-start gap-3">
          <BarChart3 className="mt-0.5 h-4 w-4 text-(--t-2)" />
          <div className="space-y-1">
            <p className="text-xs font-black uppercase tracking-wider text-(--t-1)">
              Not enough similar projects yet.
            </p>
            <p className="text-xs text-(--t-2)">
              Benchmarks will unlock automatically after the cohort reaches privacy-safe sample
              thresholds.
            </p>
          </div>
        </div>
      </GlassCard>
    );
  }

  return (
    <GlassCard className="p-5 border-primary/30 bg-primary/10">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="space-y-1">
          <p className="text-[10px] font-black uppercase tracking-[0.2em] text-primary">
            Benchmark Intelligence
          </p>
          <p className="text-sm font-black text-(--t-1)">
            You are in the top {benchmark.top_percent}% of similar projects.
          </p>
          <p className="text-xs text-(--t-2)">{benchmark.cohort_label ?? "Cohort benchmark"}</p>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-xl border border-(--line) bg-(--line-2) px-3 py-2">
            <p className="text-[10px] font-black uppercase tracking-widest text-(--t-2)">
              Citation Stability
            </p>
            <p className="text-lg font-black text-(--t-1)">
              {formatScore(citationStability?.value)}
            </p>
          </div>
          <div className="rounded-xl border border-(--line) bg-(--line-2) px-3 py-2">
            <p className="text-[10px] font-black uppercase tracking-widest text-(--t-2)">
              Remediation Impact
            </p>
            <p className="text-lg font-black text-(--t-1)">
              {formatScore(remediationImpact?.value)}
            </p>
          </div>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-2 text-[10px] font-black uppercase tracking-wider text-[color-mix(in_srgb,var(--t-2)_80%,transparent)]">
        <Activity className="h-3.5 w-3.5 text-primary" />
        Cohort size: {benchmark.cohort_size}
      </div>
    </GlassCard>
  );
}
