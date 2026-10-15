"use client";

import Link from "next/link";
import React from "react";
import { useTranslation } from "react-i18next";
import { Info } from "lucide-react";

import Tooltip from "@/components/ui/Tooltip";

import AuditRunStages from "@/components/results/AuditRunStages";
import AuditSection from "@/components/results/AuditSection";
import SignalAlert from "@/components/signal/SignalAlert";
import { cx } from "@/components/ui/utils";
import type { AuditLiveDebateProgress, AuditRunSnapshot } from "@/hooks/useAuditRunner";
import {
  findFailedStageRow,
  resolveScanDuration,
  resolveScanStageRows,
  type ScanVisibilityStat,
} from "@/lib/auditScanRun";
import { formatDate } from "@/lib/dateFormatShared";
import type { AuditHistoryItem } from "@/types/auditWorkspace";

export type CompletedScanScores = {
  auditId: number;
  aioScore: number | null;
  seoScore: number | null;
};

type AuditScanRunViewProps = {
  snapshot: AuditRunSnapshot;
  debateProgress: AuditLiveDebateProgress | null;
  completed: CompletedScanScores | null;
  /** Most recent earlier scan for the same target, or null when there is none. */
  previousScan: AuditHistoryItem | null;
  /**
   * The project's measured AI visibility, or its honest unmeasured state.
   * `null` when the scan has no project behind it (so there is nothing to
   * read) and while the summary is still being read.
   */
  visibility: ScanVisibilityStat | null;
  /**
   * Scans left on the plan after this run. `null` means the plan has no cap;
   * `undefined` means the allowance is not known, and the cost sentence then
   * states only the scan this run used.
   */
  scansRemaining: number | null | undefined;
  /**
   * Where "Back to dashboard" goes. The approved design points it at the
   * scan's own project dashboard (mockup: Signal Audit Run.html links to
   * Signal Overview.html, the project dashboard), so the caller passes
   * `/dashboard/projects/<id>` once the project is known (SIGV2-1164). The
   * workspace overview is the fallback while it is not.
   */
  dashboardHref?: string;
  onRetry: () => void;
  onChangeOptions: () => void;
};

const BTN =
  "inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3]";
const BTN_PRIMARY =
  "inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black";
const BTN_GHOST =
  "inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-[10px] border border-transparent bg-transparent px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-2) hover:bg-(--line-2) hover:text-(--t-1)";

const scoreOrNull = (value: number | null | undefined): number | null =>
  typeof value === "number" && Number.isFinite(value) ? Math.round(value) : null;

/** Grouped like the approved alert's "1,856", in the reader's own locale. */
const formatScanCount = (value: number): string => new Intl.NumberFormat().format(value);

/**
 * One "New scores" stat: the measured value, and beside it the signed delta
 * and direction arrow the approved design carries on every stat
 * (SIGV2-1123).
 *
 * `delta === null` means there is no comparable baseline, so nothing is
 * printed beside the value at all. A delta of 0 is printed, because "no
 * movement" is a measured outcome, and it carries no arrow because there is
 * no direction to state.
 *
 * `fine` is the one-line basis note the sibling report surface already uses on
 * a figure that is not this scan's own measurement. `measured` false renders
 * the value as the product's unmeasured word rather than at figure size, so it
 * never reads as a number.
 */
function ScoreFigure({
  label,
  value,
  delta,
  fine,
  note,
  noteLabel,
  measured = true,
  statKey,
}: {
  label: string;
  value: string | number;
  delta: number | null;
  fine?: string | null;
  // SIGV2-1295: provenance, in a tooltip rather than under the number.
  // `fine` says what the score means, in the same few words its neighbours
  // use. Where a figure also has to explain which run produced it, that
  // sentence goes here, because carrying it inline wrapped the caption to
  // four lines against its neighbours' two and lifted the whole row.
  note?: string | null;
  noteLabel?: string;
  measured?: boolean;
  statKey: string;
}) {
  const { t } = useTranslation();
  const direction = delta === null || delta === 0 ? null : delta > 0 ? "up" : "down";
  return (
    <div data-scan-stat={statKey}>
      <div className="text-xs text-(--t-3)">{label}</div>
      <div
        className={cx(
          "font-(family-name:--disp) font-extrabold",
          measured ? "text-[30px]" : "text-[15px] text-(--t-3)"
        )}
      >
        {value}
        {delta !== null && (
          <span
            data-scan-delta={direction ?? "unchanged"}
            className={cx(
              "ms-2 font-(family-name:--mono) text-[13px] font-medium",
              direction === "up"
                ? "text-(--good)"
                : direction === "down"
                  ? "text-(--bad)"
                  : "text-(--t-3)"
            )}
          >
            {delta > 0 ? `+${delta}` : String(delta)}
            {direction ? (
              <>
                {" "}
                <span aria-hidden="true">{direction === "up" ? "\u2191" : "\u2193"}</span>
                <span className="sr-only">
                  {t(
                    direction === "up"
                      ? "signalScanRun.succeeded.deltaUp"
                      : "signalScanRun.succeeded.deltaDown"
                  )}
                </span>
              </>
            ) : (
              <span className="sr-only"> {t("signalScanRun.succeeded.deltaUnchanged")}</span>
            )}
          </span>
        )}
      </div>
      {fine ? (
        <div className="mt-1.5 flex max-w-[24ch] items-start gap-1 text-[11.5px] leading-[1.35] text-(--t-3)">
          <span className="min-w-0">{fine}</span>
          {note ? (
            <Tooltip content={note} triggerAriaLabel={noteLabel} side="top">
              <Info size={11} strokeWidth={2} aria-hidden="true" className="mt-[2px] flex-none" />
            </Tooltip>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/**
 * The approved scan run view (mockup: Signal Audit Run.html) in its three
 * states.
 *
 * The approved third stat, AI visibility, is the project's own measured
 * figure, not a measurement of this scan: a scan produces no visibility
 * percentage of its own (the scan-scoped read path exists,
 * `GET .../monitoring/visibility-summary?audit_job_id=...` scoping to
 * VisibilityRunBatch.audit_job_id, SIGV2-1010, but nothing on the audit path
 * ever sets that column, and a per-scan measurement is deliberately not
 * triggered). So the stat states the project's current figure from
 * ProjectVisibilityService.build_summary and names monitoring as its basis in
 * the same words the report page's third figure uses, with the measurement's
 * own date when the payload carries one. Its delta is the payload's own
 * `trend_delta`, the move between the two most recent measured points, and is
 * dropped entirely when the series has no second point. With no completed
 * monitoring run the stat says so in the product's unmeasured word, and a scan
 * with no project behind it shows two stats.
 *
 * One figure the mockup shows is deliberately absent, because the audit does
 * not produce it: the mockup's three "What changed" sentences (engine
 * citations, competitor gap, fixes opened and closed). Nothing persists an
 * audit-to-audit delta those sentences could be read from. The score movements
 * below are real derivations from the previous scan for the same target; the
 * prose is not invented to fill the card.
 *
 * The failed state also carries no charge statement. The approved mockup
 * promises "Nothing was charged", and the backend does not keep that promise:
 * a scan is consumed at job acceptance and the allowance counts every
 * AuditJob row in the window regardless of outcome
 * (backend/services/scan_allowance_service.py). Printing the refund promise
 * would be a lie, so it is not printed.
 */
export default function AuditScanRunView({
  snapshot,
  debateProgress,
  completed,
  previousScan,
  visibility,
  scansRemaining,
  dashboardHref = "/dashboard",
  onRetry,
  onChangeOptions,
}: AuditScanRunViewProps) {
  const { t } = useTranslation();
  const rows = React.useMemo(() => resolveScanStageRows(snapshot.stages), [snapshot.stages]);

  if (snapshot.phase === "running") {
    return (
      <div className="space-y-3.5">
        <AuditSection
          id="audit-run-stages"
          heading={t("signalScanRun.stages.heading")}
          description={t("signalScanRun.stages.description")}
        >
          <AuditRunStages rows={rows} debateProgress={debateProgress} />
        </AuditSection>
        <SignalAlert tone="info" title={t("signalScanRun.safeToLeave.title")}>
          {t("signalScanRun.safeToLeave.body")}
        </SignalAlert>
      </div>
    );
  }

  if (snapshot.phase === "failed") {
    const failedRow = findFailedStageRow(rows);
    return (
      <div className="space-y-3.5">
        <SignalAlert tone="danger" role="alert" title={t("signalScanRun.failed.title")}>
          {failedRow
            ? t("signalScanRun.failed.summaryStage", {
                stage: t(`signalScanRun.stages.${failedRow.id}`),
              })
            : t("signalScanRun.failed.summary")}
          {snapshot.error ? ` ${snapshot.error}` : ""}
        </SignalAlert>
        <AuditSection
          id="audit-run-what-happened"
          heading={t("signalScanRun.failed.whatHappenedHeading")}
          description={t("signalScanRun.failed.whatHappenedDescription")}
        >
          <AuditRunStages rows={rows} debateProgress={debateProgress} />
        </AuditSection>
        <div className="flex flex-wrap items-center gap-2.5">
          <button type="button" onClick={onRetry} className={BTN_PRIMARY}>
            {t("signalScanRun.failed.retry")}
          </button>
          <button type="button" onClick={onChangeOptions} className={BTN}>
            {t("signalScanRun.failed.changeOptions")}
          </button>
        </div>
      </div>
    );
  }

  const duration = resolveScanDuration(snapshot.startedAt, snapshot.completedAt);
  const auditId = completed?.auditId ?? snapshot.auditId;
  const aioScore = scoreOrNull(completed?.aioScore);
  const seoScore = scoreOrNull(completed?.seoScore);
  const previousAio = previousScan
    ? scoreOrNull(
        [previousScan.aeoScore, previousScan.geoScore].every((value) => typeof value === "number")
          ? ((previousScan.aeoScore as number) + (previousScan.geoScore as number)) / 2
          : null
      )
    : null;
  const previousSeo = previousScan ? scoreOrNull(previousScan.seoScore) : null;

  // `undefined` means the payload carried no allowance at all, so the cost
  // sentence states only the scan this run used; `null` means the plan has no
  // scan cap, so there is no remainder to count down.
  const allowanceSentence =
    scansRemaining === undefined
      ? t("signalScanRun.succeeded.scanUsed")
      : scansRemaining === null
        ? t("signalScanRun.succeeded.scanUsedUnlimited")
        : t("signalScanRun.succeeded.scanUsedLeft", {
            remaining: formatScanCount(scansRemaining),
          });

  // The one-line basis note under the AI visibility stat, in the same words
  // the report page's third figure uses. A measured figure names monitoring as
  // its source and carries the measurement's own date when the payload has
  // one; an unmeasured one states why there is no figure.
  const visibilityFine =
    visibility === null
      ? null
      : visibility.state === "measured"
        ? t("signalScanRun.succeeded.aiVisibilityFine")
        : visibility.reason === "locked"
          ? t("signalScanRun.succeeded.aiVisibilityFineLocked")
          : t("signalScanRun.succeeded.aiVisibilityFineNoRun");

  // Which run produced the figure, as a tooltip. Only a measured figure has a
  // provenance to state; an unmeasured one already says why in `fine`.
  const visibilityNote =
    visibility === null || visibility.state !== "measured"
      ? null
      : visibility.measuredAt
        ? t("signalScanRun.succeeded.aiVisibilityProvenanceDated", {
            date: formatDate(visibility.measuredAt),
          })
        : t("signalScanRun.succeeded.aiVisibilityProvenance");

  const changes: string[] = [];
  if (aioScore !== null && previousAio !== null && aioScore !== previousAio) {
    changes.push(
      t("signalScanRun.succeeded.changedScore", {
        label: t("signalScanRun.succeeded.aioScore"),
        from: previousAio,
        to: aioScore,
      })
    );
  }
  if (seoScore !== null && previousSeo !== null && seoScore !== previousSeo) {
    changes.push(
      t("signalScanRun.succeeded.changedScore", {
        label: t("signalScanRun.succeeded.seoScore"),
        from: previousSeo,
        to: seoScore,
      })
    );
  }

  return (
    <div className="space-y-3.5">
      {/* The approved alert is two short sentences: how long it took, then
          what it cost. The shared ScanAllowanceNote states the limit and the
          reset date as well, which is three facts too many here, so this
          surface says only what the mockup says (SIGV2-1123). The unit is
          scans, not the mockup's "audits": that rename is deliberate. */}
      <SignalAlert tone="success" title={t("signalScanRun.succeeded.title")}>
        {duration
          ? t("signalScanRun.succeeded.finishedIn", {
              duration: t(`signalScanRun.${duration.unit}`, { count: duration.count }),
            })
          : t("signalScanRun.succeeded.finished")}{" "}
        {allowanceSentence}
      </SignalAlert>

      <div className="grid gap-4 md:grid-cols-2">
        <AuditSection
          id="audit-run-new-scores"
          heading={t("signalScanRun.succeeded.scoresHeading")}
          description={
            previousScan
              ? t("signalScanRun.succeeded.scoresVsPrevious", {
                  date: formatDate(previousScan.createdAt),
                })
              : t("signalScanRun.succeeded.scoresNoPrevious")
          }
        >
          {aioScore === null && seoScore === null ? (
            <p className="m-0 text-xs leading-[1.5] text-(--t-3)">
              {t("signalScanRun.succeeded.scoresPending")}
            </p>
          ) : (
            /* The approved `.cmp-row` 26px gap. Tops are aligned rather than
               bottoms, so the AI visibility stat's one-line basis note hangs
               below its figure instead of lifting the other two off the
               shared figure line. */
            <div className="flex flex-wrap items-start gap-[26px]">
              {aioScore !== null && (
                <ScoreFigure
                  statKey="aio"
                  label={t("signalScanRun.succeeded.aioScore")}
                  value={aioScore}
                  delta={previousAio === null ? null : aioScore - previousAio}
                />
              )}
              {seoScore !== null && (
                <ScoreFigure
                  statKey="seo"
                  label={t("signalScanRun.succeeded.seoScore")}
                  value={seoScore}
                  delta={previousSeo === null ? null : seoScore - previousSeo}
                />
              )}
              {visibility && (
                <ScoreFigure
                  statKey="aiVisibility"
                  label={t("signalScanRun.succeeded.aiVisibility")}
                  measured={visibility.state === "measured"}
                  value={
                    visibility.state === "measured"
                      ? `${visibility.percent}%`
                      : t("signalScanRun.succeeded.aiVisibilityNotMeasured")
                  }
                  delta={visibility.state === "measured" ? visibility.delta : null}
                  fine={visibilityFine}
                  note={visibilityNote}
                  noteLabel={t("signalScanRun.succeeded.aiVisibilityProvenanceLabel")}
                />
              )}
            </div>
          )}
        </AuditSection>

        <AuditSection
          id="audit-run-what-changed"
          heading={t("signalScanRun.succeeded.changedHeading")}
          description={t("signalScanRun.succeeded.changedDescription")}
        >
          {changes.length > 0 ? (
            changes.map((line) => (
              <p key={line} className="m-0 mb-2 text-xs leading-[1.5] text-(--t-3) last:mb-0">
                {line}
              </p>
            ))
          ) : (
            <p className="m-0 text-xs leading-[1.5] text-(--t-3)">
              {previousScan
                ? t("signalScanRun.succeeded.changedNone")
                : t("signalScanRun.succeeded.changedNoBaseline")}
            </p>
          )}
        </AuditSection>
      </div>

      <div className="flex flex-wrap items-center gap-2.5">
        {auditId !== null && (
          <>
            <Link href={`/dashboard/audit/${auditId}#report-sec-aeo`} className={BTN_PRIMARY}>
              {t("signalScanRun.succeeded.openAio")}
            </Link>
            <Link href={`/dashboard/audit/${auditId}#report-sec-seo`} className={BTN}>
              {t("signalScanRun.succeeded.openSeo")}
            </Link>
            <Link href={`/dashboard/audit/${auditId}#report-sec-fixes`} className={BTN}>
              {t("signalScanRun.succeeded.openFixes")}
            </Link>
          </>
        )}
        <Link href={dashboardHref} className={BTN_GHOST}>
          {t("signalScanRun.succeeded.backToDashboard")}
        </Link>
      </div>
    </div>
  );
}
