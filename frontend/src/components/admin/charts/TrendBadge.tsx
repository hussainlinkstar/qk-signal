"use client";

import React from "react";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";

type TrendBadgeProps = {
  changePct: number | null | undefined;
  /** Override label instead of showing percentage */
  label?: string;
  className?: string;
};

const CHIP =
  "inline-flex items-center gap-1 rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";

export default function TrendBadge({ changePct, label, className = "" }: TrendBadgeProps) {
  if (changePct === null || changePct === undefined) {
    return (
      <span className={`${CHIP} text-(--t-3) bg-(--line-2) ${className}`}>
        <Minus size={10} /> N/A
      </span>
    );
  }

  const isPositive = changePct > 0;
  const isZero = changePct === 0;

  const colorClasses = isZero
    ? "text-(--t-2) bg-(--line-2)"
    : isPositive
      ? "text-(--good) bg-(--good-s)"
      : "text-(--bad) bg-(--bad-s)";

  const Icon = isZero ? Minus : isPositive ? TrendingUp : TrendingDown;
  const displayText = label ?? `${isPositive ? "+" : ""}${changePct.toFixed(1)}%`;

  return (
    <span className={`${CHIP} ${colorClasses} ${className}`}>
      <Icon size={10} />
      {displayText}
    </span>
  );
}
