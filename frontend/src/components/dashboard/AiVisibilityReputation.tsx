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
import SignalScoreRing from "@/components/signal/SignalScoreRing";
import type { VisibilitySummaryResponse } from "@/types/monitoring";

const STATUS_TOKEN: Record<string, string> = {
  excellent: "bg-[#ECFDF5] text-[#059669]",
  warning: "bg-[#FFFBEB] text-[#D97706]",
  critical: "bg-[#FFF1F2] text-[#E11D48]",
};

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
    iconBg: "#ECFDF5",
    iconFg: "#059669",
  },
  {
    key: "sourceCitations",
    icon: <FileText size={16} strokeWidth={2} aria-hidden="true" />,
    iconBg: "#EFF6FF",
    iconFg: "#2563EB",
  },
  {
    key: "engineCoverage",
    icon: <Search size={16} strokeWidth={2} aria-hidden="true" />,
    iconBg: "#F5F3FF",
    iconFg: "#7C3AED",
  },
  {
    key: "brandMentions",
    icon: <CircleDot size={16} strokeWidth={2} aria-hidden="true" />,
    iconBg: "#FFFBEB",
    iconFg: "#D97706",
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
      className="flex items-center gap-3 rounded-[14px] px-3 py-3 transition-colors hover:bg-[#F8FAFC]"
      data-metric-key={def.key}
    >
      <span
        className="flex h-9 w-9 flex-none items-center justify-center rounded-[12px]"
        style={{ background: def.iconBg, color: def.iconFg }}
      >
        {def.icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-semibold text-[#111827]">{title}</div>
        <div className="text-[11.5px] text-(--t-3)">{sub}</div>
        <span className="mt-2 block h-1.5 w-full max-w-[140px] overflow-hidden rounded-full bg-[#EEF1F6]">
          <span
            className="block h-full rounded-full"
            style={{ width: `${metric.pct}%`, background: color.hex }}
          />
        </span>
      </div>
      <div className="flex flex-col items-end gap-1.5">
        <span className="font-(family-name:--disp) text-[15px] font-extrabold leading-none text-[#111827]">
          {metric.value}
        </span>
        <span
          className={cx(
            "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-[10px] font-semibold",
            STATUS_TOKEN[color.level]
          )}
        >
          {color.label}
        </span>
      </div>
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
      className="flex items-center gap-3 rounded-[14px] px-3 py-3 transition-colors hover:bg-[#F8FAFC]"
      data-metric-key={def.key}
    >
      <span
        className="flex h-9 w-9 flex-none items-center justify-center rounded-[12px]"
        style={{ background: def.iconBg, color: def.iconFg }}
      >
        {def.icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-semibold text-[#111827]">{title}</div>
        <div className="text-[11.5px] text-(--t-3)">{sub}</div>
      </div>
      <div className="flex flex-col items-end gap-1 text-end">
        <span className="rounded-full bg-[#EEF1F6] px-2.5 py-0.5 text-[11px] font-semibold text-(--t-3)">
          —
        </span>
        <span className="max-w-[160px] text-[10.5px] leading-[1.35] text-(--t-3)">{reason}</span>
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
    <div className="flex flex-col rounded-[16px] bg-[#F8FAFC] p-4 text-start">
      <div className="mb-1 flex items-center gap-2 font-(family-name:--disp) text-[13.5px] font-bold text-[#111827]">
        {icon}
        {title}
      </div>
      <div className="text-[11.5px] text-(--t-3)">{sub}</div>
      {score !== null && color ? (
        <>
          <div className="mt-3 font-(family-name:--disp) text-[28px] font-extrabold leading-none text-[#111827]">
            {Math.round(score)}
            <sub className="text-[11px] font-semibold text-(--t-3)">/100</sub>
          </div>
          <div className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-[#EEF1F6]">
            <div
              className="h-full rounded-full"
              style={{ width: `${score}%`, background: color.hex }}
            />
          </div>
        </>
      ) : (
        <>
          <div className="mt-3 font-(family-name:--disp) text-[28px] font-extrabold leading-none text-(--t-3)">
            —
          </div>
          <div className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-[#EEF1F6]" />
          <div className="mt-2 text-[11px] leading-[1.4] text-(--t-3)">
            {t("signalOverview.notMeasured")} — {reason}
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

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 md:items-stretch">
        <div className="rounded-[22px] border-0 bg-white px-5 py-5">
          <div className="flex flex-col gap-4">
            <div className="rounded-[16px] bg-[#F8FAFC] p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="font-(family-name:--disp) text-[14px] font-bold text-[#111827]">
                  {t("signalOverview.vrOverall")}
                </div>
                {aioScore !== null && scoreColor ? (
                  <span className="rounded-full bg-white px-2.5 py-0.5 text-[11px] font-semibold text-[#111827]">
                    {scoreColor.label}
                  </span>
                ) : null}
              </div>
              <div className="mt-1 text-[11.5px] leading-[1.4] text-(--t-2)">
                {t("signalOverview.vrOverallDesc")}
              </div>
              <div className="mt-3.5 flex items-center gap-4">
                <SignalScoreRing
                  score={aioScore}
                  size={72}
                  color="#3B82F6"
                  emptyLabel={
                    <span className="px-1 text-center font-(family-name:--body-font) text-[9px] font-semibold leading-[1.25] text-(--t-3)">
                      {t("signalOverview.notChecked")}
                    </span>
                  }
                />
                {opportunity ? (
                  <div className="flex flex-1 items-start gap-2 rounded-[12px] bg-white px-3 py-2.5 text-[11.5px] leading-[1.45] text-(--t-2)">
                    <span className="flex h-7 w-7 flex-none items-center justify-center rounded-[9px] bg-[#F5F3FF] text-[#7C3AED]">
                      <Sparkles size={14} aria-hidden="true" />
                    </span>
                    <div>
                      <b className="mb-0.5 block font-bold text-[#111827]">
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
                <span className="flex h-7 w-7 flex-none items-center justify-center rounded-[9px] bg-[#ECFDF5] text-[#059669]">
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

        <div className="flex h-full flex-col rounded-[22px] border-0 bg-white px-4 py-5 sm:px-5">
          <div className="flex items-baseline gap-2 px-1 font-(family-name:--disp) text-[14px] font-bold text-[#111827]">
            {t("signalOverview.vrVisibility")}
            <span className="font-(family-name:--body-font) text-[11.5px] font-normal text-(--t-3)">
              {t("signalOverview.vrFind")}
            </span>
          </div>
          <div className="mt-3 flex flex-1 flex-col gap-0.5">
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
