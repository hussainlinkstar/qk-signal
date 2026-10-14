"use client";

import React, { useId } from "react";

import { getScoreColor } from "@/lib/scoreColors";

const TRACK = "#E6E9EE";

const GRADIENTS = {
  excellent: ["#86EFAC", "#15803D"],
  warning: ["#FDE68A", "#D97706"],
  critical: ["#FECACA", "#DC2626"],
} as const;

export function formatRingScore(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return "-";
  const rounded = Math.round(value * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : String(rounded);
}

export default function ScoreRing({
  value,
  display,
  size = 84,
  stroke = 8,
  label,
}: {
  value: number | null;
  display?: React.ReactNode;
  size?: number;
  stroke?: number;
  label?: string;
}) {
  const rawId = useId().replace(/:/g, "");
  const gradientId = `score-ring-${rawId}`;
  const measured = value != null && Number.isFinite(value);
  const pct = measured ? Math.max(0, Math.min(100, value as number)) : 0;
  const level = measured ? getScoreColor(pct).level : "critical";
  const [from, to] = GRADIENTS[level];
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const filled = (pct / 100) * circumference;
  const center = size / 2;

  return (
    <span
      className="relative inline-flex shrink-0 items-center justify-center"
      style={{ width: size, height: size }}
      role="img"
      aria-label={label}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <defs>
          <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={from} />
            <stop offset="100%" stopColor={to} />
          </linearGradient>
        </defs>
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke={TRACK}
          strokeWidth={stroke}
        />
        {measured && pct > 0 ? (
          <circle
            cx={center}
            cy={center}
            r={radius}
            fill="none"
            stroke={`url(#${gradientId})`}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${filled} ${circumference - filled}`}
            transform={`rotate(-90 ${center} ${center})`}
          />
        ) : null}
      </svg>
      <span className="absolute font-(family-name:--disp) text-[22px] font-extrabold leading-none tracking-[-0.03em] text-(--t-1)">
        {display ?? formatRingScore(value)}
      </span>
    </span>
  );
}
