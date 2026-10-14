"use client";

import React, { useId } from "react";

/** Approved `.pc-spark` / `.gspark` sparkline: a 2px line over an 18% fill
    fading to nothing. One renderer for both surfaces that draw a project's
    score history, the workspace overview's project cards and the project
    overview's gauges (SIGV2-1181), so the two cannot draw the same series
    differently.

    Fewer than two points is not a thin line, it is no line: the caller decides
    what to say instead, this renders nothing. */
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
  // `useId` so two sparklines sharing an accent cannot share a gradient id.
  const gradientId = `pc-spark-${useId().replace(/:/g, "")}`;
  if (points.length < 2) return null;
  const pad = 3;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const step = (width - pad * 2) / (points.length - 1);
  const coords = points.map((value, index) => {
    const x = pad + index * step;
    const y = height - pad - ((value - min) / range) * (height - pad * 2);
    return [x, y] as const;
  });
  const line = coords
    .map(([x, y], index) => `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`)
    .join(" ");
  const last = coords[coords.length - 1];
  const first = coords[0];
  const area = `${line} L${last[0].toFixed(1)},${height} L${first[0].toFixed(1)},${height} Z`;

  return (
    <svg
      className={className}
      // The plotted series, as the approved markup carries it (`data-spark`):
      // the drawn path is unreadable, this keeps the real numbers inspectable.
      data-spark={points.join(",")}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.18" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gradientId})`} data-signal-enter="sparkfill" />
      <path
        d={line}
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
        data-signal-enter="path"
      />
    </svg>
  );
}
