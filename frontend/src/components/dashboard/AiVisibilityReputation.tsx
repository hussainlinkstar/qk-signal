"use client";

import React from "react";
import { CircleDot, FileText, MessageCircle, Search, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getScoreColor } from "@/lib/scoreColors";
import {
  deriveWiredMetrics,
  type DerivedMetric,
  type WiredMetricKey,
} from "@/lib/visibilityMetrics";
import { cx } from "@/components/ui/utils";
import type { VisibilitySummaryResponse } from "@/types/monitoring";

const RING_C = 2 * Math.PI * 26;

const STATUS_TOKEN: Record<string, string> = {
  excellent: "bg-(--good-s) text-(--good)",
  warning: "bg-(--warn-s) text-(--warn)",
  critical: "bg-(--bad-s) text-(--bad)",
};

// signal-MVP `.metric` icons/accents per approved row.
type MetricDef = {
  key: string;
  icon: React.ReactNode;
  iconBg: string;
  iconFg: string;
};

const VISIBILITY_METRICS: MetricDef[] = [
  {
    key: "answerPresence",
    icon: <MessageCircle size={16} strokeWidth={2} aria-hidden="true" />,
    iconBg: "rgba(18,161,80,.1)",
    iconFg: "var(--good)",
  },
  {
    key: "sourceCitations",
    icon: <FileText size={16} strokeWidth={2} aria-hidden="true" />,
    iconBg: "rgba(18,161,80,.1)",
    iconFg: "var(--good)",
  },
  {
    key: "engineCoverage",
    icon: <Search size={16} strokeWidth={2} aria-hidden="true" />,
    iconBg: "rgba(18,161,80,.1)",
    iconFg: "var(--good)",
  },
  {
    key: "brandMentions",
    icon: <CircleDot size={16} strokeWidth={2} aria-hidden="true" />,
    iconBg: "rgba(18,161,80,.1)",
    iconFg: "var(--good)",
  },
];

function MeasuredMetric({
  def,
  title,
  sub,
  metric,
}: {
  def: MetricDef;
  title: string;
  sub: string;
  metric: DerivedMetric;
}) {
  const color = getScoreColor(metric.pct);
  return (
    <div
      className="flex items-center gap-3.5 border-t border-t-(--line-2) px-5 py-[15px] first-of-type:border-t-0"
      data-metric-key={def.key}
    >
      <span
        className="flex h-9 w-9 flex-none items-center justify-center rounded-full"
        style={{ background: def.iconBg, color: def.iconFg }}
      >
        {def.icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-semibold">{title}</div>
        <div className="text-[11.5px] text-(--t-3)">{sub}</div>
      </div>
      {/* Approved `.mval` + `.m-status`: the measured value, its bar, and the
          score-band status. The mock's `.m-compare` peer line has no source and
          is not rendered. */}
      <div className="flex flex-col items-end gap-1.5">
        <span className="font-(family-name:--disp) text-[15px] font-black leading-none">
          {metric.value}
        </span>
        <span className="h-1.5 w-[86px] overflow-hidden rounded-full bg-(--line)">
          <span
            className="block h-full rounded-full"
            style={{ width: `${metric.pct}%`, background: color.hex }}
          />
        </span>
      </div>
      <span
        className={cx(
          "inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] px-2 py-0.5 font-mono text-[10px] tracking-[0.04em]",
          STATUS_TOKEN[color.level]
        )}
      >
        {color.label}
      </span>
    </div>
  );
}

function UnmeasuredMetric({
  def,
  title,
  sub,
  reason,
}: {
  def: MetricDef;
  title: string;
  sub: string;
  reason: string;
}) {
  return (
    <div
      className="flex items-center gap-3.5 border-t border-t-(--line-2) px-5 py-[15px] first-of-type:border-t-0"
      data-metric-key={def.key}
    >
      <span
        className="flex h-9 w-9 flex-none items-center justify-center rounded-full"
        style={{ background: def.iconBg, color: def.iconFg }}
      >
        {def.icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-semibold">{title}</div>
        <div className="text-[11.5px] text-(--t-3)">{sub}</div>
      </div>
      {/* The mock shows a value, bar, status and peer comparison here. None of
          them has a resolvable source on this surface, so the row names why. */}
      <div className="flex flex-col items-end gap-1 text-end">
        <span className="font-(family-name:--disp) text-[15px] font-black text-(--t-3)">-</span>
        <span className="max-w-[190px] text-[10.5px] leading-[1.35] text-(--t-3)">{reason}</span>
      </div>
    </div>
  );
}

function TintColumn({
  icon,
  title,
  sub,
  reason,
  score,
}: {
  icon: React.ReactNode;
  title: string;
  sub: string;
  reason: string;
  score: number | null;
}) {
  const { t } = useTranslation();
  const color = score !== null ? getScoreColor(score) : null;
  return (
    <div className="flex flex-col rounded-[14px] bg-[#F6F8FB] p-5 text-start">
      <div className="mb-1 flex items-center gap-[7px] font-(family-name:--disp) text-[13.5px] font-bold">
        {icon}
        {title}
      </div>
      <div className="text-[11.5px] text-(--t-3)">{sub}</div>
      {score !== null && color ? (
        <>
          <div className="mt-2.5 font-(family-name:--disp) text-[30px] font-black leading-none">
            {Math.round(score)}
            <sub className="font-mono text-[11px] font-normal text-(--t-3)">/100</sub>
          </div>
          <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-(--line)">
            <div
              className="h-full rounded-full"
              style={{ width: `${score}%`, background: color.hex }}
            />
          </div>
        </>
      ) : (
        <>
          <div className="mt-2.5 font-(family-name:--disp) text-[30px] font-black leading-none text-(--t-3)">
            -
          </div>
          <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-(--line)" />
          <div className="mt-2 text-[11px] leading-[1.4] text-(--t-3)">
            {t("signalOverview.notMeasured")} - {reason}
          </div>
        </>
      )}
    </div>
  );
}

/**
 * "AI visibility & reputation" - the approved `.vr` layout: the `.vr-summary`
 * column on the left, the VISIBILITY rows on the right. The overall ring (the
 * real AIO score) and the biggest opportunity (the top prioritised fix) come
 * from the latest audit; the "Does AI find you?" score and the four rows come
 * from the visibility-monitoring summary, which is plan-gated and may have no
 * completed run, so those slots render an explicit unmeasured state naming
 * why rather than substituting an unrelated number.
 */
export default function AiVisibilityReputation({
  aioScore,
  opportunity,
  summary,
}: {
  aioScore: number | null;
  opportunity: string | null;
  summary: VisibilitySummaryResponse | null;
}) {
  const { t } = useTranslation();
  const scoreColor = aioScore !== null ? getScoreColor(aioScore) : null;
  const pct = aioScore ?? 0;
  const wired = summary ? deriveWiredMetrics(summary) : null;
  const visibilityLocked = summary?.entitlements.is_locked === true;

  return (
    <section aria-label={t("signalOverview.vrTitle")}>
      <div className="mb-3.5 flex flex-wrap items-center gap-3">
        <h2 className="m-0 font-(family-name:--disp) text-[17px] font-extrabold tracking-[-0.01em]">
          {t("signalOverview.vrTitle")}
        </h2>
        <span className="h-4 w-px flex-none bg-(--line-2)" />
        <span className="text-[12.5px] text-(--t-3)">{t("signalOverview.vrSub")}</span>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <div className="rounded-(--r) border border-(--line) bg-(--panel)">
          <div className="flex flex-col gap-4 px-[18px] py-4">
            <div className="flex flex-col rounded-[14px] p-2">
              <div className="flex items-start justify-between gap-4">
                <div className="font-(family-name:--disp) text-[14px] font-bold">
                  {t("signalOverview.vrOverall")}
                </div>
                <div>
                  {aioScore !== null && scoreColor ? (
                    <div className="font-(family-name:--disp) text-[14px] font-extrabold">
                      {scoreColor.label}
                    </div>
                  ) : null}
                  <div className="mt-0.5 text-[11.5px] leading-[1.4] text-(--t-2)">
                    {t("signalOverview.vrOverallDesc")}
                  </div>
                </div>
              </div>
              <div className="mt-2.5 flex items-center gap-[18px]">
                <div className="relative h-16 w-16 flex-none">
                  <svg className="h-16 w-16 -rotate-90" viewBox="0 0 64 64" aria-hidden="true">
                    <defs>
                      <linearGradient id="gVR" x1="0" y1="0" x2="1" y2="1">
                        <stop offset="0" stopColor="var(--blue)" />
                        <stop offset="1" stopColor="var(--purple)" />
                      </linearGradient>
                    </defs>
                    <circle
                      cx="32"
                      cy="32"
                      r="26"
                      fill="none"
                      stroke="var(--line)"
                      strokeWidth="6"
                    />
                    <circle
                      cx="32"
                      cy="32"
                      r="26"
                      fill="none"
                      stroke="url(#gVR)"
                      strokeWidth="6"
                      strokeLinecap="round"
                      strokeDasharray={RING_C}
                      strokeDashoffset={RING_C * (1 - pct / 100)}
                    />
                  </svg>
                  <div className="absolute inset-0 flex flex-col items-center justify-center font-(family-name:--disp) text-[17px] font-black leading-none">
                    {aioScore !== null ? (
                      aioScore
                    ) : (
                      /* SIGV2-1097: name the unmeasured state, never a bare dash. */
                      <span className="px-1 text-center font-(family-name:--body-font) text-[9px] font-semibold leading-[1.25] text-(--t-3)">
                        {t("signalOverview.notChecked")}
                      </span>
                    )}
                    {aioScore !== null ? (
                      <small className="font-mono text-[9px] font-normal text-(--t-3)">/100</small>
                    ) : null}
                  </div>
                </div>
                {opportunity ? (
                  <div className="flex flex-1 items-start gap-2 rounded-[10px] bg-[#F6F8FB] px-3 py-2.5 text-[11.5px] leading-[1.45] text-(--t-2)">
                    <Sparkles
                      size={15}
                      className="mt-0.5 flex-none text-(--purple)"
                      aria-hidden="true"
                    />
                    <div>
                      <b className="mb-0.5 block font-bold text-(--t-1)">
                        {t("signalOverview.vrOpportunity")}
                      </b>
                      {opportunity}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
            <TintColumn
              icon={
                <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-[rgba(16,185,129,.14)] text-[#0E9F6E]">
                  <Search size={13} strokeWidth={2} aria-hidden="true" />
                </span>
              }
              title={t("signalOverview.vrFind")}
              sub={t("signalOverview.vrFindSub")}
              reason={t("signalOverview.vrReasonMonitoring")}
              score={
                !visibilityLocked && (summary?.completed_checks ?? 0) > 0
                  ? (summary?.visibility_score ?? null)
                  : null
              }
            />
          </div>
        </div>

        <div className="rounded-(--r) border border-(--line) bg-(--panel)">
          <div className="flex items-baseline gap-2 px-5 pt-4 font-(family-name:--disp) text-[13px] font-bold tracking-[0.06em]">
            {t("signalOverview.vrVisibility")}
            <span className="font-(family-name:--body-font) text-[11.5px] font-normal tracking-normal text-(--t-3)">
              {t("signalOverview.vrFind")}
            </span>
          </div>
          <div className="mt-3">
            {VISIBILITY_METRICS.map((def) => {
              const metric = wired?.[def.key as WiredMetricKey] ?? null;
              if (metric) {
                return (
                  <MeasuredMetric
                    key={def.key}
                    def={def}
                    title={t(`signalOverview.${def.key}`)}
                    sub={t(`signalOverview.${def.key}Sub`)}
                    metric={metric}
                  />
                );
              }
              return (
                <UnmeasuredMetric
                  key={def.key}
                  def={def}
                  title={t(`signalOverview.${def.key}`)}
                  sub={t(`signalOverview.${def.key}Sub`)}
                  reason={t(
                    visibilityLocked
                      ? `signalOverview.${def.key}Reason`
                      : "signalOverview.vrReasonNoData"
                  )}
                />
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
