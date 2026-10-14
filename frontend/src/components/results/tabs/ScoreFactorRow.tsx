"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { ArrowRight, ChevronRight } from "lucide-react";

import { getScoreColor } from "@/lib/scoreColors";
import { cx } from "@/components/ui/utils";

/**
 * One factor of a score, on the approved `.st` row anatomy (SIGV2-1317).
 *
 * Declared values from `signal.css`, the block `Signal SEO Detail.html` uses
 * to answer "what makes up this score":
 *
 *   .st        border-top 1px var(--line-2)
 *   .st .sh    padding 16px 22px, gap 14px
 *   .st .num   display font, 900, 26px, width 52px, tracking -.02em
 *   .st .sn .t display font, 700, 14.5px
 *   .st .sn .d 12.5px, --t-3
 *   .st .sbar  150px wide, 7px tall, radius 999px, bg --line
 *   .st .body  padding 2px 22px 20px 74px
 *   .st .lab   mono 10.5px, tracking .08em, uppercase, --t-3
 *
 * Lifted out of `SeoTab`, where it was local, so the AIO score is explained
 * the same way the SEO score is. Razvan's point: AEO and GEO were two
 * separate sections while `computeAioScore` averages them into the one AIO
 * number printed above, so the page contradicted its own arithmetic. They are
 * two factors of one score, and a factor of a score already has an approved
 * shape. This is it.
 *
 * The 74px body indent is approved **here**, because it lines a factor's
 * detail up under its own number. It was not approved on the disclosure body,
 * where it indented a whole section away from its own heading; that one is
 * removed in the same ticket.
 */

export type ScoreFactor = {
  id: string;
  title: string;
  description: string;
  /** `null` is "not measured", and renders as such rather than as a zero. */
  score: number | null;
  why: string;
  evidence?: string[];
  fixes?: string[];
  checks?: { title: string; score: number }[];
};

/** `.st`: rows separated by a hairline, the first without one. */
const ROW_CLASS = "border-t border-(--line-2) first:border-t-0";
/** `.st .sh` */
const HEAD_CLASS =
  "flex w-full items-center gap-[14px] px-[22px] py-4 text-start transition-colors hover:bg-(--line-2)";
/** `.st .num` */
const NUM_CLASS =
  "w-[52px] flex-none font-(family-name:--disp) text-[26px] font-black leading-none tracking-[-0.02em]";
/** `.st .body .lab` */
const LABEL_CLASS = "mt-3 mb-1.5 font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";

export default function ScoreFactorRow({
  factor,
  /** Namespaces the body id and the test hook, so two scores can coexist. */
  group,
}: {
  factor: ScoreFactor;
  group: string;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = React.useState(false);
  const bodyId = `${group}-factor-${factor.id}`;
  const measured = factor.score !== null;
  const colour = measured ? getScoreColor(factor.score as number).hex : undefined;

  return (
    <div className={ROW_CLASS} data-score-factor={factor.id} data-score-group={group}>
      <button
        type="button"
        className={HEAD_CLASS}
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((value) => !value)}
      >
        {measured ? (
          <span className={NUM_CLASS} style={{ color: colour }}>
            {Math.round(factor.score as number)}
          </span>
        ) : (
          // The number slot is 52px at 26px. "Not measured" does not fit there,
          // and the overflow paints on top of the title beside it.
          <span className="w-[6.75rem] shrink-0 text-[13px] font-semibold leading-tight text-(--t-3)">
            {t("signalSeoFactors.notMeasured")}
          </span>
        )}

        <span className="min-w-0 flex-1">
          <span className="block font-(family-name:--disp) text-[14.5px] font-bold text-(--t-1)">
            {factor.title}
          </span>
          <span className="mt-0.5 block text-[12.5px] text-(--t-3)">{factor.description}</span>
        </span>

        {/* `.st .sbar`: 150px, 7px tall. Only drawn for a measured factor,
            because an empty bar invites the reader to read zero. */}
        {measured ? (
          <span className="hidden h-[7px] w-[150px] flex-none overflow-hidden rounded-full bg-(--line) sm:block">
            <i
              className="block h-full w-(--factor-bar) rounded-full"
              style={
                {
                  "--factor-bar": `${Math.max(0, Math.min(100, Math.round(factor.score as number)))}%`,
                  backgroundColor: colour,
                } as React.CSSProperties
              }
            />
          </span>
        ) : null}

        <ChevronRight
          size={18}
          strokeWidth={2}
          aria-hidden="true"
          className={cx("flex-none text-(--t-3) transition-transform", open && "rotate-90")}
        />
      </button>

      {open ? (
        <div id={bodyId} className="px-[22px] pb-5 ps-[74px] pt-0.5">
          <div className={LABEL_CLASS}>{t("signalSeoFactors.whyTitle")}</div>
          <p className="m-0 text-[13px] leading-[1.55] text-(--t-2)">{factor.why}</p>

          {factor.evidence?.length ? (
            <ul className="mt-1.5 list-none p-0">
              {factor.evidence.map((line) => (
                <li key={line} className="py-[3px] text-[12.5px] text-(--t-3)">
                  {line}
                </li>
              ))}
            </ul>
          ) : null}

          {factor.checks?.length ? (
            <ul className="mt-2 list-none p-0">
              {factor.checks.map((check) => {
                const percent = Math.round(check.score * 100);
                return (
                  <li
                    key={check.title}
                    className="flex items-center gap-3 border-t border-(--line-2) py-2 text-[13px] text-(--t-1) first:border-t-0"
                  >
                    <span className="min-w-0 flex-1">{check.title}</span>
                    <span
                      className="font-mono text-[11.5px]"
                      style={{ color: getScoreColor(percent).hex }}
                    >
                      {percent}%
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : null}

          {factor.fixes?.length ? (
            <>
              <div className={LABEL_CLASS}>{t("signalSeoFactors.howTitle")}</div>
              <ul className="mt-1.5 list-none p-0">
                {factor.fixes.map((fix) => (
                  <li
                    key={fix}
                    className="flex items-start gap-[9px] py-[5px] text-[13px] text-(--t-1)"
                  >
                    <ArrowRight
                      size={15}
                      strokeWidth={2}
                      aria-hidden="true"
                      className="mt-0.5 flex-none text-(--purple)"
                    />
                    <span className="min-w-0">{fix}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
