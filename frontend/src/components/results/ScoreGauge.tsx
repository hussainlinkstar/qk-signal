"use client";

import React, { useEffect, useState } from "react";
import { motion, useMotionValue, useReducedMotion, useSpring, useTransform } from "motion/react";
import { getScoreColor } from "@/lib/scoreColors";

type ScoreGaugeProps = {
  score: number;
  label: string;
  inline?: boolean;
  /** Previous score for delta display */
  previousScore?: number;
  /** Tooltip text explaining what this score measures */
  tooltip?: string;
  /** Whether to animate the gauge from 0 to the target score on mount */
  animate?: boolean;
  /** Custom size width and height in px */
  size?: number;
};

const ScoreGauge = ({
  score,
  label,
  inline = false,
  previousScore,
  tooltip,
  animate = false,
  size,
}: ScoreGaugeProps) => {
  const defaultSize = inline ? 48 : 96;
  const targetSize = size ?? defaultSize;
  const radius = targetSize * (inline ? 0.375 : 0.375); // approx scales based on original logic
  const strokeWidth = inline ? 4 : 8;
  const sizeClass = inline ? "w-12 h-12" : "w-24 h-24";
  const svgClass = "w-full h-full";
  const fontSize = inline ? "text-xs" : "text-2xl";

  const circumference = 2 * Math.PI * radius;
  const targetOffset = circumference - (score / 100) * circumference;
  const center = targetSize / 2;

  // The spring is JS-driven (rAF), so Playwright's CSS-level
  // `animations: disabled` cannot settle it - reducedMotion is the only
  // signal that reaches it, which also serves real reduced-motion users.
  const prefersReducedMotion = useReducedMotion();
  const shouldAnimate = animate && !prefersReducedMotion;

  // Animation values
  const scoreValue = useMotionValue(0);
  const springScore = useSpring(scoreValue, { duration: 1.2, bounce: 0 }); // 1.2s smooth animation

  // State to hold the rounded display number so it updates continuously
  const [displayScore, setDisplayScore] = useState(0);

  useEffect(() => {
    if (shouldAnimate) {
      scoreValue.set(score);
    } else {
      scoreValue.set(score);
      setDisplayScore(Math.round(score));
    }
  }, [shouldAnimate, score, scoreValue]);

  useEffect(() => {
    if (shouldAnimate) {
      const unsubscribe = springScore.on("change", (latest) => {
        setDisplayScore(Math.round(latest));
      });
      return () => unsubscribe();
    }
  }, [shouldAnimate, springScore]);

  // Transform spring score to stroke offset
  const animatedOffset = useTransform(springScore, [0, 100], [circumference, 0]);

  // Derive stroke color as a MotionValue so framer-motion applies it on
  // every animation frame (plain strings in style={} get stale on motion.*)
  const animatedStroke = useTransform(
    springScore,
    (latest: number) => getScoreColor(Math.round(latest)).hex
  );

  const getScoreTextClass = (value: number) => getScoreColor(value).text;
  const getStrokeColor = (value: number) => getScoreColor(value).hex;
  const getRating = (value: number) => getScoreColor(value).label;

  // Delta calculation
  const delta = previousScore !== undefined ? Math.round(score - previousScore) : null;
  const deltaStr =
    delta !== null ? (delta > 0 ? `+${delta}` : delta === 0 ? "0" : `${delta}`) : null;
  const deltaColor =
    delta !== null
      ? delta > 0
        ? "text-green-400"
        : delta < 0
          ? "text-red-400"
          : "text-(--t-3)"
      : "";

  // Title/tooltip
  const titleText = tooltip ?? `${label}: ${Math.round(score)}/100, ${getRating(score)}`;

  if (inline) {
    return (
      <div className="flex items-center gap-3" title={titleText}>
        <span className="sr-only">
          {label} Score: {Math.round(score)} out of 100
        </span>
        <div
          className={`relative inline-flex items-center justify-center overflow-hidden rounded-full ${sizeClass}`}
          style={size ? { width: size, height: size } : {}}
          aria-hidden="true"
        >
          <svg className={svgClass} viewBox={`0 0 ${targetSize} ${targetSize}`}>
            <circle
              className="text-(--t-3)"
              strokeWidth={strokeWidth}
              stroke="currentColor"
              fill="transparent"
              r={radius}
              cx={center}
              cy={center}
            />
            <motion.circle
              strokeWidth={strokeWidth}
              strokeDasharray={circumference}
              className="[stroke-dashoffset:var(--do)] [stroke:var(--sk)]"
              style={
                {
                  "--do": shouldAnimate ? animatedOffset : targetOffset,
                  "--sk": shouldAnimate ? animatedStroke : getStrokeColor(score),
                } as React.CSSProperties
              }
              strokeLinecap="round"
              fill="transparent"
              r={radius}
              cx={center}
              cy={center}
              transform={`rotate(-90 ${center} ${center})`}
            />
          </svg>
          <span
            className={`absolute ${fontSize} font-bold ${getScoreTextClass(shouldAnimate ? displayScore : score)}`}
          >
            {Math.round(shouldAnimate ? displayScore : score)}
          </span>
        </div>
        <div aria-hidden="true">
          <p className="text-sm font-medium text-(--t-2)">{label}</p>
          {deltaStr && (
            <p className={`text-[10px] font-semibold ${deltaColor}`}>{deltaStr} vs. last</p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center text-center" title={titleText}>
      <span className="sr-only">
        {label} Score: {Math.round(score)} out of 100
      </span>
      <div
        className={`relative inline-flex items-center justify-center overflow-hidden rounded-full ${sizeClass}`}
        style={size ? { width: size, height: size } : {}}
        aria-hidden="true"
      >
        <svg className={svgClass} viewBox={`0 0 ${targetSize} ${targetSize}`}>
          <circle
            className="text-(--t-3)"
            strokeWidth={strokeWidth}
            stroke="currentColor"
            fill="transparent"
            r={radius}
            cx={center}
            cy={center}
          />
          <motion.circle
            strokeWidth={strokeWidth}
            strokeDasharray={circumference}
            className="[stroke-dashoffset:var(--do)] [stroke:var(--sk)]"
            style={
              {
                "--do": shouldAnimate ? animatedOffset : targetOffset,
                "--sk": shouldAnimate ? animatedStroke : getStrokeColor(score),
              } as React.CSSProperties
            }
            strokeLinecap="round"
            fill="transparent"
            r={radius}
            cx={center}
            cy={center}
            transform={`rotate(-90 ${center} ${center})`}
          />
        </svg>
        <span
          className={`absolute ${fontSize} font-bold ${getScoreTextClass(shouldAnimate ? displayScore : score)}`}
        >
          {Math.round(shouldAnimate ? displayScore : score)}
        </span>
      </div>
      <p className="mt-2 text-sm font-semibold text-(--t-2)" aria-hidden="true">
        {label}
      </p>
      {deltaStr && (
        <p className={`mt-0.5 text-[10px] font-semibold ${deltaColor}`} aria-hidden="true">
          {deltaStr} vs. last
        </p>
      )}
    </div>
  );
};

export default ScoreGauge;
