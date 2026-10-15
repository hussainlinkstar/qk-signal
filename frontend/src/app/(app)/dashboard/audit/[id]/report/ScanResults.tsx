"use client";

import React from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";

import ReportSection from "./ReportSection";
import ScoreRing, { formatRingScore } from "./ScoreRing";
import ScoreDeltaBadge from "@/components/results/ScoreDeltaBadge";
import { buttonClasses } from "@/components/ui/Button";
import Tooltip from "@/components/ui/Tooltip";
import { ArrowRight, Info } from "lucide-react";
import { cx } from "@/components/ui/utils";
import { formatDate } from "@/lib/dateFormat";
import { deriveAuditChangeLines } from "@/lib/auditChangeLines";
import { getScoreColor } from "@/lib/scoreColors";
import type { AuditComparisonResponse, ScoreDelta } from "@/hooks/useAuditComparison";

// signal-MVP `.card.sblock`: panel fill, 1px --line, radius --r, padding 20/22.
const CARD_CLASS = "rounded-[22px] border-0 bg-white px-[18px] py-3";
// signal-MVP `.sblock h3` and `.sblock .sd`.
const CARD_TITLE_CLASS = "m-0 mb-[3px] font-(family-name:--disp) text-[14.5px] font-bold";
const CARD_SUB_CLASS = "mb-4 text-[12.5px] text-(--t-3)";

export type AiVisibilityFigure = {
  score: number;
  measuredAt: string | null;
};

function Figure({
  label,
  score,
  fine,
  note,
  noteLabel,
  delta,
  previousDate,
}: {
  label: string;
  score: number | null;
  fine: string;
  // SIGV2-1295: provenance that belongs in a tooltip, not under the number.
  // The AI visibility figure carried its whole provenance sentence as `fine`,
  // 80 characters in a 22ch column, so it wrapped to four lines while its two
  // neighbours wrapped to two. The row aligns on the tallest item, so one long
  // caption lifted the scores beside it.
  note?: string;
  noteLabel?: string;
  delta?: ScoreDelta;
  previousDate?: string | null;
}) {
  return (
    <div className="flex min-w-0 flex-1 flex-col items-center text-center">
      <ScoreRing value={score} display={formatRingScore(score)} size={84} label={label} />
      <div className="mt-2 text-[12px] text-(--t-3)">{label}</div>
      {delta?.delta != null ? (
        <div className="mt-1">
          <ScoreDeltaBadge
            delta={delta.delta}
            direction={delta.direction}
            previousScore={delta.previous}
            previousDate={previousDate ?? null}
            size="sm"
          />
        </div>
      ) : null}
      <div className="mt-1.5 flex w-full items-start justify-center gap-1 text-center text-[12px] leading-[1.4] text-(--t-3)">
        <span className="min-w-0">{fine}</span>
        {note ? (
          <Tooltip content={note} triggerAriaLabel={noteLabel} side="top">
            <Info size={12} strokeWidth={2} aria-hidden="true" className="mt-[2px] flex-none" />
          </Tooltip>
        ) : null}
      </div>
    </div>
  );
}

/**
 * The results block of a finished check, in the approved order: "New scores",
 * then "What changed", then the four next steps, then the full detail.
 *
 * Two figures always have a source: the AIO score and the SEO score of this
 * check. The third figure the design shows, AI visibility, is produced by the
 * monitoring worker from the project's tracked prompts, not by this check, so
 * it renders only when a completed monitoring run exists and names that basis
 * on the card. It is never a blank third card.
 */
export default function ScanResults({
  aioScore,
  seoScore,
  aioDelta,
  seoDelta,
  comparison,
  previousAuditDate,
  aiVisibility,
  dashboardHref = "/dashboard/overview",
  children,
}: {
  aioScore: number | null;
  seoScore: number | null;
  aioDelta?: ScoreDelta;
  seoDelta?: ScoreDelta;
  comparison?: AuditComparisonResponse | null;
  previousAuditDate?: string | null;
  aiVisibility?: AiVisibilityFigure | null;
  /**
   * Where "Back to dashboard" goes. The approved design points it at the
   * report's own project dashboard (SIGV2-1164); the workspace overview is the
   * fallback when the audit carries no project.
   */
  dashboardHref?: string;
  children?: React.ReactNode;
}) {
  const { t } = useTranslation();

  const previousDate = previousAuditDate ? formatDate(previousAuditDate) : null;
  const changeLines = deriveAuditChangeLines(comparison);
  const hasPrevious = comparison?.has_previous === true;

  return (
    <ReportSection
      eyebrow={t("signalAuditReport.scores.eyebrow")}
      title={t("signalAuditReport.scores.title")}
    >
      {/* signal-MVP `.setgrid`. */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className={CARD_CLASS}>
          <div className={CARD_SUB_CLASS}>
            {hasPrevious && previousDate
              ? t("signalAuditReport.scores.versus", { date: previousDate })
              : t("signalAuditReport.scores.noPrevious")}
          </div>
          {/* signal-MVP `.cmp-row` with the approved 26px gap, bottom aligned. */}
          <div className="flex w-full items-start justify-between gap-4">
            <Figure
              label={t("signalAuditReport.scores.aio")}
              score={aioScore}
              fine={t("signalAuditReport.scores.aioFine")}
              delta={aioDelta}
              previousDate={previousDate}
            />
            <Figure
              label={t("signalAuditReport.scores.seo")}
              score={seoScore}
              fine={t("signalAuditReport.scores.seoFine")}
              delta={seoDelta}
              previousDate={previousDate}
            />
            {aiVisibility ? (
              <Figure
                label={t("signalAuditReport.scores.aiVisibility")}
                score={Math.round(aiVisibility.score)}
                note={
                  aiVisibility.measuredAt
                    ? t("signalAuditReport.scores.aiVisibilityProvenanceDated", {
                        date: formatDate(aiVisibility.measuredAt),
                      })
                    : t("signalAuditReport.scores.aiVisibilityProvenance")
                }
                noteLabel={t("signalAuditReport.scores.aiVisibilityProvenanceLabel")}
                fine={t("signalAuditReport.scores.aiVisibilityFine")}
              />
            ) : null}
          </div>
        </div>

        {changeLines.length > 0 ? (
          <div className={CARD_CLASS}>
            <h3 className={CARD_TITLE_CLASS}>{t("signalAuditReport.changed.title")}</h3>
            <div className={CARD_SUB_CLASS}>{t("signalAuditReport.changed.description")}</div>
            <ul className="m-0 list-none space-y-2.5 p-0">
              {changeLines.map((line) => {
                const label = t(`signalAuditReport.changed.labels.${line.key}`);
                const previousColor = getScoreColor(line.previous).hex;
                const currentColor = getScoreColor(line.current).hex;
                return (
                  <li key={line.key} className="relative flex items-center gap-3">
                    <span
                      className="absolute"
                      style={{
                        position: "absolute",
                        width: 1,
                        height: 1,
                        padding: 0,
                        margin: -1,
                        overflow: "hidden",
                        clip: "rect(0, 0, 0, 0)",
                        whiteSpace: "nowrap",
                        border: 0,
                      }}
                    >
                      {t("signalAuditReport.changed.line", {
                        label,
                        previous: line.previous,
                        current: line.current,
                      })}
                    </span>
                    <span className="flex shrink-0 items-center gap-1.5">
                      <span
                        className="flex h-9 min-w-9 items-center justify-center rounded-full border px-1.5 font-(family-name:--disp) text-[13px] font-bold leading-none"
                        style={{
                          color: previousColor,
                          backgroundColor: `${previousColor}1A`,
                          borderColor: `${previousColor}66`,
                        }}
                      >
                        {line.previous}
                      </span>
                      <span aria-hidden="true" className="text-(--t-1)">
                        <ArrowRight size={18} strokeWidth={2.5} />
                      </span>
                      <span
                        className="flex h-9 min-w-9 items-center justify-center rounded-full px-1.5 font-(family-name:--disp) text-[13px] font-bold leading-none text-white"
                        style={{ backgroundColor: currentColor }}
                      >
                        {line.current}
                      </span>
                    </span>
                    <span className="min-w-0 flex-1 text-[13px] leading-snug text-(--t-1)">
                      {label}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}
      </div>

      {/* signal-MVP `.cmp-row` of next steps: `.btn pri`, `.btn`, `.btn`,
          `.btn ghost`. The first three are drill-downs on this same page, so
          they jump to the matching section instead of leaving it. */}
      <div className="flex flex-wrap items-center gap-2.5">
        <a href="#report-aio" className={buttonClasses({ variant: "primary", size: "md" })}>
          {t("signalAuditReport.next.aio")}
        </a>
        <a href="#report-seo" className={buttonClasses({ variant: "outline", size: "md" })}>
          {t("signalAuditReport.next.seo")}
        </a>
        <a href="#report-sec-fixes" className={buttonClasses({ variant: "outline", size: "md" })}>
          {t("signalAuditReport.next.fixes")}
        </a>
        <Link href={dashboardHref} className={cx(buttonClasses({ variant: "ghost", size: "md" }))}>
          {t("signalAuditReport.next.dashboard")}
        </Link>
      </div>

      {children ? (
        <div className="rounded-[22px] border-0 bg-white">{children}</div>
      ) : null}
    </ReportSection>
  );
}
