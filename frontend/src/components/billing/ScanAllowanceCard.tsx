"use client";

import React from "react";
import { TrendingDown, TrendingUp, Flame, Calendar, AlertTriangle, Coins } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassComponents";
import { cx } from "@/components/ui/utils";
import { Spinner } from "@/components/ui/Loading";
import type { UsageAnalyticsResponse } from "@/types/billing";

type Props = {
  data: UsageAnalyticsResponse | null;
  isLoading?: boolean;
  className?: string;
};

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  color = "text-(--foreground)",
}: {
  icon: React.ElementType;
  label: string;
  value: string;
  sub?: string;
  color?: string;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-(--muted-foreground)">
        <Icon className="h-3 w-3" />
        {label}
      </div>
      <p className={cx("text-xl font-semibold", color)}>{value}</p>
      {sub && <p className="text-xs text-(--muted-foreground)">{sub}</p>}
    </div>
  );
}

export default function ScanAllowanceCard({ data, isLoading, className }: Props) {
  if (isLoading || !data) {
    return (
      <GlassCard className={cx("p-6", className)}>
        <div className="flex h-32 items-center justify-center">
          <Spinner size="md" label="Computing forecast..." />
        </div>
      </GlassCard>
    );
  }

  const {
    scans_used,
    scans_remaining,
    scan_allowance,
    burn_rate_7d,
    burn_rate_30d,
    days_until_depletion,
    depletion_date,
    will_exhaust_before_renewal,
    projected_overage,
    renewal_date,
    projection_reason,
    observed_days,
  } = data;

  const pctRemaining =
    scan_allowance !== null && scan_allowance > 0 && scans_remaining !== null
      ? Math.round((scans_remaining / scan_allowance) * 100)
      : null;

  // SIGV2-1306: the comparison needs two windows that describe different
  // periods, which on a new account they do not.
  //
  // QA saw "+367% vs 30d avg" on an account days old. The arithmetic was
  // right and the comparison was empty: the daily series is padded to a full
  // window, so one scan three days ago is a 7-day rate of 1/7 and a 30-day
  // rate of 1/31. The ratio between those is about +330% whatever the usage
  // was, which makes the figure a property of the window sizes rather than of
  // the customer's behaviour.
  //
  // Thirty days of history is what "vs 30d avg" claims, so it is what the
  // comparison now requires.
  const hasComparableHistory = observed_days >= 30;
  const burnTrend =
    hasComparableHistory && burn_rate_7d > 0 && burn_rate_30d > 0
      ? Math.round(((burn_rate_7d - burn_rate_30d) / burn_rate_30d) * 100)
      : 0;

  // SIGV2-1306: why there is no projection, when there is none. "No active
  // usage" was the only thing this said, and it was wrong for an account that
  // had used the product but not for long enough to extrapolate from.
  const depletionSub = (() => {
    if (depletion_date) return `Est. ${depletion_date}`;
    switch (projection_reason) {
      case "insufficient_history":
        return observed_days > 0
          ? `Needs about a week of use to project; ${observed_days} so far`
          : "Needs about a week of use to project";
      case "allowance_uncapped":
        return "Your plan has no scan cap";
      default:
        return "No active usage";
    }
  })();

  return (
    <GlassCard className={cx("space-y-5 p-6", className)}>
      <div>
        <h3 className="text-lg font-medium text-(--foreground)">Scan allowance</h3>
        <p className="text-xs text-(--muted-foreground)">
          Projected usage based on your recent activity
        </p>
      </div>

      {/* Progress bar */}
      {scan_allowance !== null && scan_allowance > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className="text-(--muted-foreground)">
              {scans_used.toLocaleString()} / {scan_allowance.toLocaleString()} scans
            </span>
            <span
              className={cx(
                "font-medium",
                pctRemaining !== null && pctRemaining <= 20
                  ? "text-rose-400"
                  : pctRemaining !== null && pctRemaining <= 50
                    ? "text-amber-400"
                    : "text-(--foreground)"
              )}
            >
              {pctRemaining ?? 0}% remaining
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-(--surface-subtle)">
            <div
              className={cx(
                "h-full w-(--bw) rounded-full transition-all duration-500",
                pctRemaining !== null && pctRemaining <= 20
                  ? "bg-linear-to-r from-rose-500 to-rose-400"
                  : pctRemaining !== null && pctRemaining <= 50
                    ? "bg-linear-to-r from-amber-500 to-amber-400"
                    : "bg-linear-to-r from-indigo-500 to-indigo-400"
              )}
              style={{ "--bw": `${Math.min(pctRemaining ?? 0, 100)}%` } as React.CSSProperties}
            />
          </div>
        </div>
      )}

      {/* Stat grid */}
      <div className="grid grid-cols-2 gap-5 lg:grid-cols-4">
        <StatCard
          icon={Flame}
          label="Burn Rate (7d)"
          value={`${burn_rate_7d.toFixed(1)}/day`}
          sub={burnTrend !== 0 ? `${burnTrend > 0 ? "+" : ""}${burnTrend}% vs 30d avg` : undefined}
          color={burn_rate_7d > 0 ? "text-(--foreground)" : "text-(--muted-foreground)"}
        />
        <StatCard
          icon={burn_rate_7d > burn_rate_30d ? TrendingUp : TrendingDown}
          label="Burn Rate (30d)"
          value={`${burn_rate_30d.toFixed(1)}/day`}
        />
        <StatCard
          icon={Calendar}
          label="Days Until Depletion"
          value={days_until_depletion !== null ? `~${Math.round(days_until_depletion)}` : "N/A"}
          sub={depletionSub}
          color={
            days_until_depletion !== null && days_until_depletion <= 7
              ? "text-rose-400"
              : days_until_depletion !== null && days_until_depletion <= 14
                ? "text-amber-400"
                : "text-(--foreground)"
          }
        />
        <StatCard
          icon={Coins}
          label="Renewal"
          value={
            renewal_date
              ? new Date(renewal_date).toLocaleDateString("en-US", {
                  month: "short",
                  day: "numeric",
                })
              : "N/A"
          }
          sub={renewal_date ? "Next billing cycle" : "No active subscription"}
        />
      </div>

      {/* Overage warning */}
      {will_exhaust_before_renewal && projected_overage > 0 && (
        <div className="flex items-start gap-3 rounded-lg border border-amber-500/20 bg-amber-500/5 p-4">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
          <div>
            <p className="text-sm font-medium text-amber-400">
              Projected to run out before renewal
            </p>
            <p className="mt-1 text-xs text-(--muted-foreground)">
              At your current rate, you&apos;ll need ~{projected_overage.toLocaleString()}{" "}
              additional scans to reach your next billing cycle. Consider a plan upgrade.
            </p>
          </div>
        </div>
      )}
    </GlassCard>
  );
}
