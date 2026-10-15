"use client";

import React from "react";
import { ChevronRight } from "lucide-react";
import ScoreGauge from "@/components/results/ScoreGauge";
import { getScoreColor } from "@/lib/scoreColors";
import type { Pillar } from "@/lib/reportAdapters";
import { cx } from "@/components/ui/utils";

type PillarCardProps = {
  pillar: Pillar;
  isActive?: boolean;
  onClick?: () => void;
  /**
   * Deterministic, role-appropriate interpretation of the pillar score
   * (from `describeScore(...).interpretation`). Shown as the card's
   * human-readable line beneath the score; numbers stay as `X/100`.
   */
  language?: string;
  /**
   * Optional role-appropriate next action (from `describeScore(...).nextAction`).
   * Rendered as a quieter follow-on line when present.
   */
  nextAction?: string;
};

/**
 * Presentational headline card for a customer-facing pillar (SEO or AIO).
 * Renders the shared ScoreGauge donut, a progress-to-target bar, a scope
 * badge and the pillar label/score. Stateless — all data comes from `pillar`.
 */
export default function PillarCard({
  pillar,
  isActive = false,
  onClick,
  language,
  nextAction,
}: PillarCardProps) {
  const hasScore = typeof pillar.score === "number";
  const score = hasScore ? (pillar.score as number) : 0;
  const scoreColor = hasScore ? getScoreColor(score) : null;

  const target = typeof pillar.target === "number" && pillar.target > 0 ? pillar.target : 100;
  const progressPct = hasScore ? Math.max(0, Math.min(100, (score / target) * 100)) : 0;
  const hasExplicitTarget = typeof pillar.target === "number" && pillar.target > 0;

  const interactive = typeof onClick === "function";

  return (
    <div
      className={cx("relative group", interactive && "cursor-pointer")}
      onClick={onClick}
      onKeyDown={
        interactive
          ? (event: React.KeyboardEvent) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onClick?.();
              }
            }
          : undefined
      }
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      aria-pressed={interactive ? isActive : undefined}
    >
      <div
        className="absolute -inset-0.5 rounded bg-(--c) opacity-0 blur-sm transition-opacity duration-500 group-hover:opacity-20"
        style={{ "--c": pillar.color } as React.CSSProperties}
      />
      <div
        className={cx(
          "relative flex flex-col gap-6 p-6 rounded border bg-(--line-2) h-full shadow-inner transition-all duration-500 hover:bg-(--line-2)",
          isActive ? "border-(--line)" : "border-(--line)"
        )}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <span
                className="inline-block h-2 w-2 rounded-full bg-(--c)"
                style={{ "--c": pillar.color } as React.CSSProperties}
                aria-hidden="true"
              />
              <span className="text-sm font-black uppercase tracking-[0.2em] text-(--t-1)">
                {pillar.label}
              </span>
            </div>
            <span className="inline-flex w-fit items-center rounded-full border-0 bg-(--line-2) px-2.5 py-0.5 text-[9px] font-bold uppercase tracking-widest text-(--t-2)">
              {pillar.scopeLabel}
            </span>
          </div>

          <div className="shrink-0">
            {hasScore ? (
              <ScoreGauge score={score} label={pillar.label} size={72} />
            ) : (
              <div className="flex flex-col items-center justify-center w-[72px] h-[72px] rounded-full border-0 bg-(--line-2)">
                <span className="text-lg font-black text-(--t-3)">N/A</span>
              </div>
            )}
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-[9px] font-bold uppercase tracking-widest text-(--t-3)">
              {hasExplicitTarget ? `Progress to target (${target})` : "Progress to 100"}
            </span>
            <span
              className={cx(
                "text-[10px] font-black",
                scoreColor ? scoreColor.text : "text-(--t-3)"
              )}
            >
              {hasScore ? `${Math.round(score)}/100` : "N/A"}
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-(--line-2)">
            <div
              className="h-full w-(--bw) rounded-full bg-(--c) transition-all duration-700"
              style={
                {
                  "--bw": `${progressPct}%`,
                  "--c": scoreColor ? scoreColor.hex : pillar.color,
                } as React.CSSProperties
              }
            />
          </div>
        </div>

        {(language || nextAction) && (
          <div className="flex flex-col gap-1.5">
            {language && <p className="text-[11px] leading-relaxed text-(--t-2)">{language}</p>}
            {nextAction && (
              <p className="text-[10px] font-bold uppercase tracking-widest text-(--t-3)">
                {nextAction}
              </p>
            )}
          </div>
        )}

        {interactive && (
          <ChevronRight className="absolute top-4 right-4 w-4 h-4 text-(--t-3) opacity-0 group-hover:opacity-100 transition-opacity" />
        )}
      </div>
    </div>
  );
}
