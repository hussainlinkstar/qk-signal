"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { TrendingUp, TrendingDown } from "lucide-react";
import { cx } from "@/components/ui/utils";
import Tooltip from "@/components/ui/Tooltip";

type ScoreDeltaBadgeProps = {
  delta: number | null | undefined;
  direction?: "up" | "down" | "stable";
  previousScore?: number | null;
  previousDate?: string | null;
  size?: "sm" | "md";
  className?: string;
};

export default function ScoreDeltaBadge({
  delta,
  direction,
  previousScore,
  previousDate,
  size = "sm",
  className,
}: ScoreDeltaBadgeProps) {
  const { t } = useTranslation();
  if (delta == null) return null;

  const dir = direction ?? (delta > 1 ? "up" : delta < -1 ? "down" : "stable");
  const absDelta = Math.abs(Math.round(delta));
  const label =
    dir === "up"
      ? `+${absDelta}`
      : dir === "down"
        ? `\u2212${absDelta}`
        : t("signalAuditReport.deltaNoChange");

  const colorClasses =
    dir === "up"
      ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/20"
      : dir === "down"
        ? "text-red-400 bg-red-500/10 border-red-500/20"
        : "text-(--t-2) bg-(--line-2) border-(--line)";

  const Icon = dir === "up" ? TrendingUp : dir === "down" ? TrendingDown : null;

  const sizeClasses =
    size === "sm" ? "text-[10px] gap-0.5 px-1.5 py-0.5" : "text-xs gap-1 px-2 py-1";

  const iconSize = size === "sm" ? "w-2.5 h-2.5" : "w-3 h-3";

  const tooltipContent =
    previousScore != null
      ? `Previous: ${Math.round(previousScore)}/100${previousDate ? ` (${previousDate})` : ""}`
      : null;

  const badge = (
    <span
      className={cx(
        "inline-flex items-center font-bold rounded border",
        colorClasses,
        sizeClasses,
        className
      )}
    >
      {Icon ? <Icon className={iconSize} /> : null}
      {label}
    </span>
  );

  if (tooltipContent) {
    return <Tooltip content={tooltipContent}>{badge}</Tooltip>;
  }

  return badge;
}
