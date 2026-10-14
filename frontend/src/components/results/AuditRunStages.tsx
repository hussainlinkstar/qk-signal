"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { Check, Circle, X } from "lucide-react";

import { cx } from "@/components/ui/utils";
import type { AuditLiveDebateProgress } from "@/hooks/useAuditRunner";
import type { AuditStageState, ScanStageRow, ScanStageRowId } from "@/lib/auditScanRun";

const ROW_COPY: Record<ScanStageRowId, { title: string; detail: string }> = {
  crawl: {
    title: "signalScanRun.stages.crawl",
    detail: "signalScanRun.stages.crawlDetail",
  },
  technical: {
    title: "signalScanRun.stages.technical",
    detail: "signalScanRun.stages.technicalDetail",
  },
  answerEngines: {
    title: "signalScanRun.stages.answerEngines",
    detail: "signalScanRun.stages.answerEnginesDetail",
  },
  competitors: {
    title: "signalScanRun.stages.competitors",
    detail: "signalScanRun.stages.competitorsDetail",
  },
  synthesis: {
    title: "signalScanRun.stages.synthesis",
    detail: "signalScanRun.stages.synthesisDetail",
  },
};

const STATE_TONE: Record<AuditStageState, { icon: string; word: string }> = {
  pending: { icon: "border-(--line) text-(--t-3)", word: "text-(--t-3)" },
  running: { icon: "border-[#4F46E5] text-[#4F46E5]", word: "text-[#4F46E5]" },
  completed: { icon: "border-transparent bg-(--good-s) text-(--good)", word: "text-(--good)" },
  degraded: { icon: "border-(--warn) text-(--warn)", word: "text-(--warn)" },
  failed: {
    icon: "border-transparent bg-[rgba(229,72,77,0.1)] text-(--bad)",
    word: "text-(--bad)",
  },
  skipped: { icon: "border-(--line) text-(--t-3)", word: "text-(--t-3)" },
  unknown: { icon: "border-(--line) text-(--t-3)", word: "text-(--t-3)" },
};

/**
 * The approved Stages list (mockup: Signal Audit Run.html, the `.stg` rows).
 *
 * Status is reported per stage with an honest state word and no percentage,
 * which the approved page states as the rule. The counts the mockup prints in
 * the descriptions ("24 key pages", "30 prompts across 7 engines", "the 4
 * competitors") are mockup demo data and the run does not report them, so the
 * descriptions carry no number. The one count that is reported, the debate's
 * own completed-step count, is appended to Synthesis when it is live.
 */
export default function AuditRunStages({
  rows,
  debateProgress,
}: {
  rows: ScanStageRow[];
  debateProgress?: AuditLiveDebateProgress | null;
}) {
  const { t } = useTranslation();

  const reviewSteps = React.useMemo(() => {
    const steps = debateProgress?.steps ?? [];
    if (steps.length === 0) return null;
    return {
      done: steps.filter((step) => step.status === "completed").length,
      total: steps.length,
    };
  }, [debateProgress]);

  return (
    <ol className="m-0 list-none p-0">
      {rows.map((row) => {
        const tone = STATE_TONE[row.status];
        const detail =
          row.id === "synthesis" && reviewSteps
            ? t("signalScanRun.stages.reviewSteps", reviewSteps)
            : t(ROW_COPY[row.id].detail);
        return (
          <li
            key={row.id}
            data-stage={row.id}
            data-stage-state={row.status}
            className="flex items-center gap-[14px] border-b border-(--line-2) py-[14px] last:border-b-0"
          >
            <span
              aria-hidden="true"
              className={cx(
                "flex h-[30px] w-[30px] flex-none items-center justify-center rounded-full border-[1.5px]",
                tone.icon
              )}
            >
              {row.status === "completed" ? (
                <Check className="h-[15px] w-[15px]" strokeWidth={2.5} />
              ) : row.status === "failed" ? (
                <X className="h-[15px] w-[15px]" strokeWidth={2.5} />
              ) : row.status === "running" ? (
                <span className="h-3.5 w-3.5 rounded-full border-2 border-(--line-2) border-t-[#4F46E5] motion-safe:animate-spin" />
              ) : (
                <Circle className="h-[15px] w-[15px]" strokeWidth={2.5} />
              )}
            </span>
            <span className="min-w-0 flex-1">
              <b className="block text-[13.5px] font-semibold">{t(ROW_COPY[row.id].title)}</b>
              <small className="text-xs text-(--t-3)">{detail}</small>
              {row.status === "failed" && row.reason && (
                <small className="block font-(family-name:--mono) text-[10.5px] text-(--bad)">
                  {row.reason}
                </small>
              )}
            </span>
            <span
              className={cx(
                "font-(family-name:--mono) text-[10px] uppercase tracking-[0.1em]",
                tone.word
              )}
            >
              {t(`signalScanRun.stages.state.${row.status}`)}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
