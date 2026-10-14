import React from "react";
import { Minus, TrendingDown, TrendingUp } from "lucide-react";

import Badge from "@/components/ui/Badge";
import { getScoreColor, type ScoreLevel } from "@/lib/scoreColors";
import { cx } from "@/components/ui/utils";

const badgeColorByLevel: Record<ScoreLevel, React.ComponentProps<typeof Badge>["color"]> = {
  excellent: "success",
  warning: "warning",
  critical: "danger",
};

const scoreSurfaceByLevel: Record<ScoreLevel, string> = {
  excellent: "border-success/20 bg-success/10 text-success",
  warning: "border-warning/20 bg-warning/10 text-warning",
  critical: "border-danger/20 bg-danger/10 text-danger",
};

export function ScoreToneBadge({ score }: { score: number }) {
  const tone = getScoreColor(score);
  return <Badge color={badgeColorByLevel[tone.level]}>{tone.label}</Badge>;
}

export function ScoreMetricTile({
  label,
  value,
  detail,
}: {
  label: string;
  value: React.ReactNode;
  detail?: string;
}) {
  return (
    <div className="rounded border border-(--border) bg-(--surface-subtle) px-4 py-3 shadow-(--shadow-inset)">
      <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-(--text-muted)">
        {label}
      </p>
      <div className="mt-2 text-lg font-semibold text-(--foreground)">{value}</div>
      {detail ? <p className="mt-1 text-xs text-(--text-muted)">{detail}</p> : null}
    </div>
  );
}

export function ScoreIconTile({
  level,
  children,
  className,
}: {
  level: ScoreLevel;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cx(
        "flex h-11 w-11 items-center justify-center rounded border",
        scoreSurfaceByLevel[level],
        className
      )}
    >
      {children}
    </div>
  );
}

export function TrendChip({ delta }: { delta: number | null }) {
  if (delta === null) {
    return (
      <span className="inline-flex items-center gap-2 text-xs text-(--text-muted)">
        <Minus className="h-4 w-4" />
        Trend available after the next run
      </span>
    );
  }

  const isPositive = delta > 0;
  const isNegative = delta < 0;
  const icon = isPositive ? (
    <TrendingUp className="h-4 w-4" />
  ) : isNegative ? (
    <TrendingDown className="h-4 w-4" />
  ) : (
    <Minus className="h-4 w-4" />
  );
  const toneClass = isPositive
    ? "text-success"
    : isNegative
      ? "text-danger"
      : "text-(--text-muted)";

  return (
    <span className={cx("inline-flex items-center gap-2 text-xs font-medium", toneClass)}>
      {icon}
      {`${delta > 0 ? "+" : ""}${delta.toFixed(1)} pts vs previous run`}
    </span>
  );
}

export function MiniSparkline({
  values,
  stroke,
  className,
}: {
  values: number[];
  stroke: string;
  className?: string;
}) {
  if (values.length === 0) {
    return (
      <div
        className={cx(
          "flex h-20 items-center justify-center rounded border border-dashed border-(--border) bg-(--surface-subtle) text-xs text-(--text-muted)",
          className
        )}
      >
        No trend yet
      </div>
    );
  }

  if (values.length === 1) {
    return (
      <div
        className={cx(
          "flex h-20 items-center justify-center rounded border border-(--border) bg-(--surface-subtle) text-xs text-(--text-muted)",
          className
        )}
      >
        One snapshot captured
      </div>
    );
  }

  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || 1;
  const points = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * 100;
      const y = 100 - ((value - min) / range) * 100;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <div
      className={cx(
        "rounded border border-(--border) bg-(--surface-subtle) p-3 shadow-(--shadow-inset)",
        className
      )}
    >
      <svg
        aria-hidden="true"
        className="h-16 w-full"
        preserveAspectRatio="none"
        viewBox="0 0 100 100"
      >
        <defs>
          <linearGradient id="score-sparkline-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity="0.24" />
            <stop offset="100%" stopColor={stroke} stopOpacity="0" />
          </linearGradient>
        </defs>
        <polyline
          fill="none"
          points={points}
          stroke={stroke}
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="3"
        />
      </svg>
    </div>
  );
}

export type RecommendationSeverity = "watch" | "medium" | "high" | "critical";

const recommendationBadgeColor: Record<
  RecommendationSeverity,
  React.ComponentProps<typeof Badge>["color"]
> = {
  watch: "warning",
  medium: "warning",
  high: "danger",
  critical: "danger",
};

const recommendationLabel: Record<RecommendationSeverity, string> = {
  watch: "Watch",
  medium: "Priority",
  high: "High",
  critical: "Critical",
};

export function RecommendationSeverityBadge({ severity }: { severity: RecommendationSeverity }) {
  return <Badge color={recommendationBadgeColor[severity]}>{recommendationLabel[severity]}</Badge>;
}
