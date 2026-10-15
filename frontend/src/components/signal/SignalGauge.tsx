"use client";

import { motion, useMotionValue, useReducedMotion, useSpring, useTransform } from "motion/react";
import { useEffect, useState } from "react";
import {
  signalScoreLevel,
  SIGNAL_SCORE_STROKE,
} from "@/components/signal/signal-tokens";

export type SignalGaugeProps = {
  score: number;
  size?: number;
  animate?: boolean;
};

/**
 * Stylish flat score ring (signal-light). Soft center disc + pill /100 label
 * + rounded stroke caps — same treatment as Channel Mix / SignalScoreRing.
 */
export default function SignalGauge({ score, size = 120, animate = true }: SignalGaugeProps) {
  const strokeWidth = Math.max(8, Math.round(size * 0.083));
  const vb = 120;
  const r = 50;
  const circumference = 2 * Math.PI * r;

  const level = signalScoreLevel(score);
  const stroke = SIGNAL_SCORE_STROKE[level];

  const scoreValue = useMotionValue(0);
  const springScore = useSpring(scoreValue, { duration: 1.5, bounce: 0 });
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
  const valueSize =
    size >= 130 ? "text-[34px]" : size >= 100 ? "text-[28px]" : "text-[17px]";

  return (
    <div
      className="relative inline-flex h-(--sz) w-(--sz) items-center justify-center"
      style={{ "--sz": size } as React.CSSProperties}
      data-score-ring
    >
      <svg width={size} height={size} viewBox={`0 0 ${vb} ${vb}`} className="-rotate-90">
        <circle r={r} cx={vb / 2} cy={vb / 2} fill="none" stroke="#EEF1F6" strokeWidth={strokeWidth} />
        <motion.circle
          r={r}
          cx={vb / 2}
          cy={vb / 2}
          fill="none"
          stroke={stroke}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          className="[stroke-dashoffset:var(--do)]"
          style={{ "--do": shouldAnimate ? animatedOffset : targetOffset } as React.CSSProperties}
        />
      </svg>
      <div className="absolute inset-[20%] flex flex-col items-center justify-center rounded-full bg-[#F8FAFC]">
        <span
          className={`font-(family-name:--disp) font-extrabold leading-none tracking-[-0.03em] text-[#111827] ${valueSize}`}
        >
          {shouldAnimate ? displayScore : Math.round(score)}
        </span>
        <small className="mt-1.5 rounded-full bg-white px-2 py-0.5 text-[11px] font-semibold text-(--t-3)">
          /100
        </small>
      </div>
    </div>
  );
}
