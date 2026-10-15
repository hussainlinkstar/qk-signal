"use client";

import React from "react";
import Link from "next/link";
import { Info } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cx } from "@/components/ui/utils";
import {
  TooltipContent,
  TooltipProvider,
  TooltipRoot,
  TooltipTrigger,
} from "@/components/ui/Tooltip";
import { useSignalScoreEntrance } from "@/hooks/useSignalChartMotion";
import ProjectScoreSparkline from "@/components/dashboard/ProjectScoreSparkline";
import SignalScoreRing from "@/components/signal/SignalScoreRing";
import {
  AIO_TREND_COLOR,
  SEO_TREND_COLOR,
  scoreDeltaMeta,
  type ScoreTrend,
} from "@/lib/projectScoreTrend";
import { deriveWiredMetrics } from "@/lib/visibilityMetrics";
import type { VisibilitySummaryResponse } from "@/types/monitoring";

function Ring({
  score,
  variant,
  name,
  target,
  trend,
}: {
  score: number | null;
  variant: "aio" | "seo";
  name: string;
  target: number | null;
  trend: ScoreTrend | null;
}) {
  const { t } = useTranslation();
  const { ref, progress } = useSignalScoreEntrance(score);
  const animated = score === null ? null : score * progress;
  const delta = trend ? scoreDeltaMeta(trend.delta) : null;
  const rounded = trend ? Math.round(trend.delta) : 0;
  return (
    <div
      ref={ref}
      data-score-gauge
      className="relative w-[150px] flex-none text-center max-md:self-center"
    >
      <span className="pointer-events-none invisible absolute -start-3.5 top-1/2 z-[3] translate-y-[calc(-50%+5px)] whitespace-nowrap rounded-[9px] bg-(--score-target-bg) px-2.5 py-1.5 font-mono text-[10px] leading-[1.15] text-(--panel) opacity-0 transition-[opacity,transform,visibility] duration-180 group-hover/panel:visible group-hover/panel:-translate-y-1/2 group-hover/panel:opacity-100 group-focus-within/panel:visible group-focus-within/panel:-translate-y-1/2 group-focus-within/panel:opacity-100 after:absolute after:-end-1 after:top-1/2 after:h-[9px] after:w-[9px] after:-translate-y-1/2 after:rotate-45 after:rounded-[1px] after:bg-(--score-target-bg) motion-reduce:transition-none">
        {target === null
          ? t("signalOverview.noTargetSet")
          : t("signalOverview.targetSet", { score: target })}
      </span>
      <SignalScoreRing
        score={animated}
        size={132}
        color={variant === "aio" ? "#A855F7" : "#3B82F6"}
        trackColor={variant === "aio" ? "#EDE9FE" : "#DBEAFE"}
        emptyLabel={
          <span className="font-(family-name:--body-font) text-[11px] font-semibold tracking-normal text-(--t-3)">
            {t("signalOverview.notChecked")}
          </span>
        }
        className="mx-auto"
      />
      {/* Progressive change under the gauge — packed tight so the left column
          does not leave a blank band under the ring (SIGV2-1181). */}
      {trend && delta ? (
        <div className="mx-auto mt-3 w-[120px] rounded-[12px] bg-[#F8FAFC] px-2 py-2">
          <div
            data-score-trend={variant}
            className="mb-1 flex items-baseline justify-end"
          >
            <span
              className={cx("text-[11.5px] font-semibold", delta.cls)}
              aria-label={t("signalOverview.scoreTrendLabel", {
                name,
                change: rounded > 0 ? `+${rounded}` : `${rounded}`,
              })}
            >
              {delta.text}
            </span>
          </div>
          <ProjectScoreSparkline
            points={trend.points}
            color={variant === "aio" ? AIO_TREND_COLOR : SEO_TREND_COLOR}
            width={104}
            height={28}
            className="mx-auto block h-[28px] w-full"
          />
        </div>
      ) : null}
    </div>
  );
}

const STAT_INFO_TRIGGER =
  "ms-1 inline-flex h-4 w-4 flex-none items-center justify-center rounded-full text-(--t-3) hover:text-(--t-1) focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple)";

/** Keyboard-reachable (i) beside a stat label. When the explanation names a
    surface, the trigger is the link to it, so activating it lands there: a
    Radix tooltip portals its panel to the end of the document and closes on
    trigger blur, so a link rendered inside the panel would never be tabbable
    (Radix documents tooltips as non-interactive). With no destination it is a
    plain button, so the explanation stays reachable either way.

    `reason` is the unmeasured state's explanation (SIGV2-1125). It used to
    render as a third line of body text in the stat row, which made the AIO
    card three lines taller than the SEO card and pushed the two actions to
    different heights. The unmeasured state itself is unchanged and still on
    screen; only the sentence explaining it moved in here. */
function StatInfo({
  body,
  cta,
  href,
  reason,
}: {
  body: string;
  cta: string;
  href?: string;
  reason?: string;
}) {
  return (
    <TooltipProvider delayDuration={0}>
      <TooltipRoot>
        <TooltipTrigger asChild>
          {href ? (
            <Link href={href} aria-label={cta} data-stat-info className={STAT_INFO_TRIGGER}>
              <Info size={14} strokeWidth={2} aria-hidden="true" />
            </Link>
          ) : (
            <button type="button" aria-label={body} data-stat-info className={STAT_INFO_TRIGGER}>
              <Info size={14} strokeWidth={2} aria-hidden="true" />
            </button>
          )}
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-72 leading-[1.45]">
          <span className="block text-(--t-2)">{body}</span>
          {reason ? <span className="mt-1.5 block text-(--t-2)">{reason}</span> : null}
          {href ? <span className="mt-1.5 block font-semibold text-(--blue)">{cta}</span> : null}
        </TooltipContent>
      </TooltipRoot>
    </TooltipProvider>
  );
}

function StatRow({
  label,
  value,
  measured,
  info,
  statKey,
}: {
  label: string;
  value: string;
  measured: boolean;
  info?: React.ReactNode;
  statKey?: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-baseline justify-between gap-4" data-stat={statKey}>
      <span className="flex items-center text-[12.5px] text-(--t-2)">
        {label}
        {info}
      </span>
      <span className="flex min-w-0 flex-col items-end text-end">
        {/* A ratio the summary cannot support is never a 0: a 0 would assert
            we measured and found none, so the slot says "Not measured" and the
            (i) carries the reason. */}
        <span
          className={cx(
            "font-(family-name:--disp) text-[16px] font-extrabold tracking-[-0.01em]",
            !measured && "text-(--t-3)"
          )}
        >
          {measured ? value : t("signalOverview.notMeasured")}
        </span>
      </span>
    </div>
  );
}

function Panel({
  variant,
  name,
  desc,
  tag,
  score,
  target,
  trend,
  secondStat,
  roomDesc,
  suggestionsLabel,
  href,
}: {
  variant: "aio" | "seo";
  name: string;
  desc: string;
  tag: string;
  score: number | null;
  target: number | null;
  trend: ScoreTrend | null;
  secondStat?: {
    key: string;
    label: string;
    value: string | null;
    info?: React.ReactNode;
  };
  roomDesc: string;
  suggestionsLabel: string;
  href: string;
}) {
  const { t } = useTranslation();
  /* Both values are already on the card, so the distance between them is a
     subtraction, not a new measurement: unmeasured whenever either side is
     missing, and "At target" rather than a negative gap once the score is
     there. */
  const gap = score === null || target === null ? null : Math.round(target) - Math.round(score);
  return (
    <div
      className="group/panel relative flex h-full min-w-0 flex-col rounded-[22px] border-0 bg-white px-5 pt-5 pb-5 sm:px-6"
      data-panel={variant}
    >
      <div
        data-panel-heading
        className="flex flex-wrap items-center gap-2.5 border-b border-[#F3F4F6] pb-3.5"
      >
        <span
          className={cx(
            "flex h-9 w-9 flex-none items-center justify-center rounded-[12px]",
            variant === "aio" ? "bg-[#F5F3FF] text-[#7C3AED]" : "bg-[#FFFBEB] text-[#D97706]"
          )}
        >
          {variant === "aio" ? (
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              aria-hidden="true"
            >
              <path d="M12 3l2.1 6.4L20.5 11l-6.4 2.1L12 19.5l-2.1-6.4L3.5 11l6.4-1.6z" />
              <path d="M19 3l.8 2.2L22 6l-2.2.8L19 9l-.8-2.2L16 6l2.2-.8z" />
            </svg>
          ) : (
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              aria-hidden="true"
            >
              <path d="M6 20v-6M12 20V8M18 20v-9" />
            </svg>
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-(family-name:--disp) text-[17px] font-extrabold tracking-[-0.02em] text-[#111827]">
              {name}
            </span>
            <span
              className={cx(
                "rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.04em]",
                variant === "aio"
                  ? "bg-[#F5F3FF] text-[#7C3AED]"
                  : "bg-[#EFF6FF] text-[#2563EB]"
              )}
            >
              {tag}
            </span>
          </div>
          <span className="mt-0.5 block text-[12.5px] text-(--t-3)">{desc}</span>
        </div>
      </div>
      {/* Equal-height bodies: ring + copy share one row so AIO/SEO stay 50/50. */}
      <div
        data-panel-body
        className="flex flex-1 items-start gap-5 pt-4 max-md:flex-col max-md:items-center sm:gap-6"
      >
        <Ring score={score} variant={variant} name={name} target={target} trend={trend} />
        <div className="flex min-w-0 flex-1 flex-col self-stretch max-md:w-full">
          {/* Approved `.score-stats` is exactly two rows (signal.css:645): the
              gap to target, then the pillar's own stat. The target itself is
              the `.tgt-tag` on the ring, which is where the approved card puts
              it, so a third "Score target" row was both a row the design does
              not have and 26px of extra card height that pushed every section
              below this one out of alignment (SIGV2-1125). */}
          <div className="mb-3 flex flex-col gap-2 rounded-[14px] bg-[#F8FAFC] px-3.5 py-3">
            <StatRow
              statKey="gapToTarget"
              label={t("signalOverview.gapToTarget")}
              value={
                gap === null
                  ? ""
                  : gap > 0
                    ? t("signalOverview.gapPts", { gap })
                    : t("signalOverview.atTarget")
              }
              measured={gap !== null}
            />
            {secondStat ? (
              <StatRow
                statKey={secondStat.key}
                label={secondStat.label}
                info={secondStat.info}
                value={secondStat.value ?? ""}
                measured={secondStat.value !== null}
              />
            ) : null}
          </div>
          <div className="mt-1">
            <div className="font-(family-name:--disp) text-[13px] font-bold text-[#111827]">
              {t("signalOverview.roomTitle")}
            </div>
            <p className="mt-0.5 text-[12px] leading-[1.45] text-(--t-2)">{roomDesc}</p>
          </div>
          {/* `mt-auto` on the wrapper: the approved pair puts both actions on
              one line, so the action is pinned to the bottom of the card
              instead of trailing whichever card has more copy. `pt-3.5` keeps
              the approved 14px gap when the card is at its natural height. */}
          <div data-panel-action className="mt-auto pt-3.5">
            <Link
              href={href}
              className="inline-flex w-fit items-center gap-[9px] rounded-full border-0 bg-[#111827] px-5 py-2.5 text-[13px] font-semibold leading-[normal] text-white hover:bg-black max-md:min-h-11"
            >
              {suggestionsLabel}
              <svg
                className="h-4 w-4 flex-none"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                aria-hidden="true"
              >
                <circle cx="12" cy="12" r="10" />
                <path d="M10 9l3 3-3 3" />
              </svg>
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

/** "Your website visibility" - approved `.scores .spanel` pair. Rings carry
    the real AIO and SEO scores. "Appearance in AI answers" is the same
    measurement as the "Answer Presence" row further down the page, derived
    from the one shared helper so the two cannot disagree (SIGV2-1111); the
    SEO panel's second stat has no source at all and is not rendered.

    The SEO card's "Room to improvement" sentence is the pillar-specific
    equivalent of the approved AIO one, not the mockup's literal SEO line:
    that line asserts a page-1 ranking, a share of target searches and a
    backlink-authority comparison, none of which this card measures
    (SIGV2-1125). */
export default function VisibilityPanels({
  aioScore,
  seoScore,
  aioTarget,
  seoTarget,
  aioTrend,
  seoTrend,
  aioHref,
  seoHref,
  promptsHref,
  summary,
}: {
  aioScore: number | null;
  seoScore: number | null;
  aioTarget?: number | null;
  seoTarget?: number | null;
  aioTrend?: ScoreTrend | null;
  seoTrend?: ScoreTrend | null;
  aioHref: string;
  seoHref: string;
  promptsHref?: string;
  summary?: VisibilitySummaryResponse | null;
}) {
  const { t } = useTranslation();
  const appearance = summary ? deriveWiredMetrics(summary).answerPresence : null;
  const appearanceReason = summary?.entitlements.is_locked
    ? t("signalOverview.appearanceStatReasonLocked")
    : t("signalOverview.appearanceStatReasonNoRun");
  return (
    <section aria-label={t("signalOverview.visibilityTitle")} className="leading-[normal]">
      <div className="mb-3.5 flex flex-wrap items-center gap-3">
        <h2 className="m-0 font-(family-name:--disp) text-[17px] font-extrabold tracking-[-0.01em]">
          {t("signalOverview.visibilityTitle")}
        </h2>
        <span className="h-4 w-px flex-none bg-(--line-2)" aria-hidden="true" />
        <span className="text-[12.5px] text-(--t-3)">{t("signalOverview.visibilitySub")}</span>
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 md:items-stretch">
        <Panel
          variant="aio"
          name="AIO"
          desc={t("signalOverview.aioDesc")}
          tag={t("signalOverview.aioTag")}
          score={aioScore}
          target={aioTarget ?? null}
          trend={aioTrend ?? null}
          secondStat={{
            key: "appearance",
            label: t("signalOverview.appearanceStat"),
            value: appearance?.value ?? null,
            info: (
              <StatInfo
                body={t("signalOverview.appearanceStatInfo")}
                cta={t("signalOverview.appearanceStatInfoCta")}
                href={promptsHref}
                reason={appearance ? undefined : appearanceReason}
              />
            ),
          }}
          roomDesc={t("signalOverview.roomDescAio")}
          suggestionsLabel={t("signalOverview.aioSuggestions")}
          href={aioHref}
        />
        <Panel
          variant="seo"
          name="SEO"
          desc={t("signalOverview.seoDesc")}
          tag={t("signalOverview.seoTag")}
          score={seoScore}
          target={seoTarget ?? null}
          trend={seoTrend ?? null}
          roomDesc={t("signalOverview.roomDescSeo")}
          suggestionsLabel={t("signalOverview.seoSuggestions")}
          href={seoHref}
        />
      </div>
    </section>
  );
}
