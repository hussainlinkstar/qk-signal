"use client";

import React from "react";
import { motion, useReducedMotion } from "motion/react";
import { Info, type LucideIcon } from "lucide-react";

import Card from "@/components/ui/Card";
import Tooltip from "@/components/ui/Tooltip";
import { CARD_LABEL_CLASS } from "@/components/ui/cardStyleTokens";
import { getScoreColor } from "@/lib/scoreColors";
import { ScoreIconTile, ScoreToneBadge } from "@/components/dashboard/scorePrimitives";

type ScoreCardProps = {
  label: string;
  value?: number | null;
  description: string;
  Icon: LucideIcon;
  metricHints: string[];
  isLoading?: boolean;
  error?: string | null;
  isEmpty?: boolean;
};

export default function ScoreCard({
  label,
  value,
  description,
  Icon,
  metricHints,
  isLoading = false,
  error = null,
  isEmpty = false,
}: ScoreCardProps) {
  const shouldReduceMotion = useReducedMotion();
  const numericValue = typeof value === "number" ? Math.round(value) : null;
  const tone = numericValue !== null ? getScoreColor(numericValue) : null;

  const tooltipContent = (
    <>
      <strong className="mb-1 block text-(--t-1)">{label} metric hints</strong>
      <ul className="list-disc space-y-1 pl-4">
        {metricHints.map((hint) => (
          <li key={hint}>{hint}</li>
        ))}
      </ul>
    </>
  );

  return (
    <motion.div
      animate={{ opacity: 1, y: 0 }}
      initial={shouldReduceMotion ? false : { opacity: 0, y: 6 }}
      transition={shouldReduceMotion ? { duration: 0 } : { duration: 0.28, ease: "easeOut" }}
    >
      <Card className="space-y-4 p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-2">
            <p className={CARD_LABEL_CLASS}>{label}</p>
            {isLoading ? (
              <div
                className="mt-2 h-8 w-16 animate-pulse rounded bg-(--line-2)"
                aria-hidden="true"
              />
            ) : error ? (
              <p className="text-sm font-medium text-danger" role="status" aria-live="polite">
                N/A
              </p>
            ) : isEmpty || numericValue === null ? (
              <p
                className="text-sm font-medium text-(--text-soft)"
                role="status"
                aria-live="polite"
              >
                N/A
              </p>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <p className={`text-4xl font-semibold tracking-tight ${tone?.text}`}>
                  {numericValue}
                </p>
                <ScoreToneBadge score={numericValue} />
              </div>
            )}
            <p className="text-sm leading-6 text-(--text-soft)">{description}</p>
          </div>

          <div className="inline-flex items-center gap-2">
            <ScoreIconTile level={tone?.level ?? "warning"}>
              <Icon className="h-5 w-5" strokeWidth={2.15} />
            </ScoreIconTile>
            <Tooltip
              content={tooltipContent}
              panelClassName="bottom-auto left-auto right-0 top-full mt-2 w-64 translate-x-0 text-left"
              triggerAriaLabel={`How ${label} is evaluated`}
            >
              <span className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-(--border) bg-(--surface-subtle) text-(--text-soft) transition hover:border-(--border-hover) hover:text-(--foreground)">
                <Info className="h-3.5 w-3.5" />
              </span>
            </Tooltip>
          </div>
        </div>
      </Card>
    </motion.div>
  );
}
