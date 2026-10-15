"use client";

import React from "react";

/**
 * Modern spark bars for score history — rounded vertical bars with a
 * stronger last point. Renders nothing with fewer than two points.
 */
export default function ProjectScoreSparkline({
  points,
  color,
  width = 120,
  height = 40,
  className = "ml-1 h-10 min-w-0 flex-1",
}: {
  points: number[];
  color: string;
  width?: number;
  height?: number;
  className?: string;
}) {
  if (points.length < 2) return null;

  const padX = 2;
  const padY = 4;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const slot = (width - padX * 2) / points.length;
  const barW = Math.max(3, Math.min(8, slot * 0.55));
  const plotH = height - padY * 2;

  return (
    <svg
      className={className}
      data-spark={points.join(",")}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      {points.map((value, index) => {
        const h = Math.max(4, ((value - min) / range) * plotH);
        const x = padX + index * slot + (slot - barW) / 2;
        const y = height - padY - h;
        const isLast = index === points.length - 1;
        return (
          <rect
            key={index}
            x={x.toFixed(2)}
            y={y.toFixed(2)}
            width={barW.toFixed(2)}
            height={h.toFixed(2)}
            rx={barW / 2}
            ry={barW / 2}
            fill={color}
            opacity={isLast ? 1 : 0.28}
            data-signal-enter="sparkfill"
          />
        );
      })}
    </svg>
  );
}
