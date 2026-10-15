"use client";

import React from "react";

import { getScoreColor } from "@/lib/scoreColors";

const LEVEL_STROKE = {
  excellent: "#059669",
  warning: "#D97706",
  critical: "#E11D48",
} as const;

export function formatRingScore(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const rounded = Math.round(value * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : String(rounded);
}

/** Stylish flat score ring — soft center + rounded stroke caps. */
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
  const measured = value != null && Number.isFinite(value);
  const pct = measured ? Math.max(0, Math.min(100, value as number)) : 0;
  const level = measured ? getScoreColor(pct).level : "critical";
  const strokeColor = LEVEL_STROKE[level];
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const filled = (pct / 100) * circumference;
  const center = size / 2;
  const valueSize = size >= 100 ? "text-[28px]" : size >= 80 ? "text-[22px]" : "text-[17px]";

  return (
    <span
      className="relative inline-flex shrink-0 items-center justify-center"
      style={{ width: size, height: size }}
      role="img"
      aria-label={label}
      data-score-ring
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke="#EEF1F6"
          strokeWidth={stroke}
        />
        {measured && pct > 0 ? (
          <circle
            cx={center}
            cy={center}
            r={radius}
            fill="none"
            stroke={strokeColor}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${filled} ${circumference - filled}`}
            transform={`rotate(-90 ${center} ${center})`}
          />
        ) : null}
      </svg>
      <span className="absolute inset-[18%] flex flex-col items-center justify-center rounded-full bg-[#F8FAFC]">
        <span
          className={`font-(family-name:--disp) font-extrabold leading-none tracking-[-0.03em] text-[#111827] ${valueSize}`}
        >
          {display ?? formatRingScore(value)}
        </span>
      </span>
    </span>
  );
}
