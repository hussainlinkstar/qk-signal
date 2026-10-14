"use client";

import { motion, useMotionValue, useReducedMotion, useSpring, useTransform } from "motion/react";
import { useEffect, useState } from "react";
import {
  signalScoreLevel,
  SIGNAL_SCORE_STROKE,
  SIGNAL_SCORE_TEXT_CLASS,
} from "@/components/signal/signal-tokens";

export type SignalGaugeProps = {
  score: number;
  size?: number;
  animate?: boolean;
};

/**
 * signal-light equivalent of components/results/ScoreGauge.tsx, kept as a
 * separate component rather than modifying ScoreGauge in place — ScoreGauge
 * has many existing dark-theme call sites (results tabs, project overview,
 * etc.) that are out of scope for this rewrite; duplicating the small amount
 * of ring math here avoids any risk of regressing those. Matches signal-MVP's
 * `.gwrap svg.g` ring (see /Users/user/signal-MVP/signal.css lines 66-70,
 * animation in app.js's `.ring-fill` handling, lines ~203-207).
 */
export default function SignalGauge({ score, size = 120, animate = true }: SignalGaugeProps) {
  const strokeWidth = 8;
  const radius = size / 2 - strokeWidth;
  const center = size / 2;
  const circumference = 2 * Math.PI * radius;

  const level = signalScoreLevel(score);
  const stroke = SIGNAL_SCORE_STROKE[level];
  const textClass = SIGNAL_SCORE_TEXT_CLASS[level];

  const scoreValue = useMotionValue(0);
  const springScore = useSpring(scoreValue, { duration: 1.5, bounce: 0 });
  // JS springs ignore Playwright's CSS-level animation disabling; reduced
  // motion is the only context signal that reaches them (and serves real
  // reduced-motion users too).
  const prefersReducedMotion = useReducedMotion();
  const shouldAnimate = animate && !prefersReducedMotion;
  const [displayScore, setDisplayScore] = useState(shouldAnimate ? 0 : Math.round(score));

  useEffect(() => {
    scoreValue.set(score);
  }, [score, scoreValue]);

  useEffect(() => {
    if (!shouldAnimate) {
      setDisplayScore(Math.round(score));
      return;
    }
    const unsubscribe = springScore.on("change", (latest) => setDisplayScore(Math.round(latest)));
    return () => unsubscribe();
  }, [shouldAnimate, score, springScore]);

  const targetOffset = circumference - (score / 100) * circumference;
  const animatedOffset = useTransform(springScore, [0, 100], [circumference, 0]);

  return (
    <div
      className="relative inline-flex h-(--sz) w-(--sz) items-center justify-center"
      style={{ "--sz": size } as React.CSSProperties}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
        <circle
          r={radius}
          cx={center}
          cy={center}
          fill="none"
          stroke="#E8EAEE"
          strokeWidth={strokeWidth}
        />
        <motion.circle
          r={radius}
          cx={center}
          cy={center}
          fill="none"
          stroke={stroke}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          className="[stroke-dashoffset:var(--do)]"
          style={{ "--do": shouldAnimate ? animatedOffset : targetOffset } as React.CSSProperties}
        />
      </svg>
      <span
        className={`absolute font-(family-name:--disp) text-[34px] font-black leading-none tracking-[-0.02em] ${textClass}`}
      >
        {shouldAnimate ? displayScore : Math.round(score)}
      </span>
    </div>
  );
}
