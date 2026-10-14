"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import PlanLockNotice from "@/components/dashboard/PlanLockNotice";
import { getPlanLockContent } from "@/lib/planLocks";
import { cx } from "@/components/ui/utils";
import type { LockedAuditSection } from "@/types/auditResult";
import { REPORT_BLOCK } from "./reportBlock";

type Competitor = {
  name: string;
  score: number;
  source: string;
  confidence_score: number;
  geo_visibility: number;
  aeo_score: number;
  entity_strength: number;
  rank: number;
};

type CompetitorsTabProps = {
  competitors: Competitor[];
  competitorSummary?: Record<string, unknown>;
  lockedSection?: LockedAuditSection | null;
};

const normalizeCompetitorToken = (value: string) => value.trim().toLowerCase().replace(/\s+/g, " ");

type BenchmarkRowMeta = {
  exploratory: boolean;
  measurementSource: string | null;
};

const getBenchmarkMetadata = (competitorSummary?: Record<string, unknown>) => {
  const summary = competitorSummary ?? {};
  const benchmark =
    typeof summary.benchmark === "object" && summary.benchmark !== null
      ? (summary.benchmark as Record<string, unknown>)
      : {};
  const rows = Array.isArray(benchmark.rows) ? benchmark.rows : [];
  const rowMetaByName = new Map<string, BenchmarkRowMeta>();

  rows.forEach((row) => {
    if (typeof row !== "object" || row === null) {
      return;
    }
    const record = row as Record<string, unknown>;
    const name = typeof record.name === "string" ? record.name.trim() : "";
    if (!name || record.is_target === true) {
      return;
    }
    rowMetaByName.set(normalizeCompetitorToken(name), {
      exploratory: Boolean(record.exploratory),
      measurementSource:
        typeof record.measurement_source === "string" && record.measurement_source.trim()
          ? record.measurement_source.trim()
          : null,
    });
  });

  const mode = typeof summary.mode === "string" ? summary.mode : null;
  const message = typeof summary.message === "string" ? summary.message : null;
  return { mode, message, rowMetaByName };
};

/** Which i18n key describes how a row was measured (SIGV2-1317). */
const measurementKey = (meta: BenchmarkRowMeta | undefined, source: string) => {
  if (meta?.exploratory || source.toLowerCase().includes("estimate")) {
    return "measuredDiscovery";
  }
  if (meta?.measurementSource === "project_snapshot") return "measuredTracked";
  if (meta?.measurementSource === "audited_competitor_crawl") return "measuredCrawl";
  return meta ? "measuredTracked" : "measuredDiscovery";
};

/** The approved `.fv` initial tile: one letter, a flat tint, no image. */
const TILE_TINTS = ["#0E7C6B", "#B45309", "#5B21B6", "#2563EB", "#9333EA", "#E5484D"];

export default function CompetitorsTab({
  competitors,
  competitorSummary,
  lockedSection,
}: CompetitorsTabProps) {
  const { t } = useTranslation();

  if (lockedSection?.is_locked) {
    return (
      <PlanLockNotice
        {...getPlanLockContent("competitiveIntelligence", {
          requiredPlanLabel: lockedSection.required_plan_label?.trim(),
          title: "Competitor analysis is locked on the current plan",
          description:
            lockedSection.detail?.trim() ||
            "Upgrade this workspace to unlock competitor discovery, benchmark deltas, and historical competitive insights.",
        })}
        badgeLabel="Locked in API payload"
        align="center"
      />
    );
  }

  if (!competitors || competitors.length === 0) {
    // One sentence in the reader's own words. This used to be a 16px circle,
    // an icon, "No Competitors Detected" in shouting capitals and "The
    // generative engine did not identify primary competitors in this scan",
    // which is our vocabulary, not theirs.
    return (
      <div className={REPORT_BLOCK}>
        <p className="m-0 max-w-prose text-[13px] leading-[1.55] text-(--t-2)">
          {t("signalAuditReport.competitors.empty")}
        </p>
      </div>
    );
  }

  const { rowMetaByName } = getBenchmarkMetadata(competitorSummary);
  const sorted = [...competitors].sort((left, right) => {
    const leftRank = left.rank > 0 ? left.rank : Number.MAX_SAFE_INTEGER;
    const rightRank = right.rank > 0 ? right.rank : Number.MAX_SAFE_INTEGER;
    if (leftRank !== rightRank) return leftRank - rightRank;
    return (right.confidence_score ?? 0) - (left.confidence_score ?? 0);
  });
  const peak = Math.max(1, ...sorted.map((c) => c.geo_visibility ?? 0));

  return (
    <div className={cx(REPORT_BLOCK, "-mx-[22px] overflow-x-auto")}>
      <table className="w-full border-collapse text-start">
        <caption className="sr-only">{t("signalAuditReport.aio.compareDesc")}</caption>
        <thead>
          <tr>
            <th className="w-5 border-b border-(--line) px-[22px] py-[11px]" />
            <th className="border-b border-(--line) px-4 py-[11px] text-start font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
              {t("signalAuditReport.competitors.colCompany")}
            </th>
            <th className="border-b border-(--line) px-4 py-[11px] text-end font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
              {t("signalAuditReport.competitors.colAio")}
            </th>
            <th className="border-b border-(--line) px-4 py-[11px] text-end font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
              {t("signalAuditReport.competitors.colSeo")}
            </th>
            <th className="w-[200px] border-b border-(--line) px-4 py-[11px] text-end font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
              {t("signalAuditReport.competitors.colVisibility")}
            </th>
            <th className="border-b border-(--line) px-[22px] py-[11px] text-end font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
              {t("signalAuditReport.competitors.colMeasured")}
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((comp, index) => {
            const meta = rowMetaByName.get(normalizeCompetitorToken(comp.name));
            const key = measurementKey(meta, comp.source);
            const named = key === "measuredDiscovery";
            const share = Math.round(((comp.geo_visibility ?? 0) / peak) * 100);

            return (
              <tr key={`${comp.name}-${index}`} data-competitor-row={comp.name}>
                <td className="border-b border-(--line-2) px-[22px] py-[13px] align-middle font-(family-name:--disp) text-[18px] font-black text-(--t-3)">
                  {comp.rank > 0 ? comp.rank : "-"}
                </td>
                <td className="border-b border-(--line-2) px-4 py-[13px] align-middle">
                  <div className="flex items-center gap-3">
                    <span
                      aria-hidden="true"
                      className="flex h-[34px] w-[34px] flex-none items-center justify-center rounded-[9px] font-(family-name:--disp) text-[15px] font-bold text-white"
                      style={{ backgroundColor: TILE_TINTS[index % TILE_TINTS.length] }}
                    >
                      {comp.name.trim().charAt(0).toUpperCase()}
                    </span>
                    <span className="min-w-0 text-[13px] text-(--t-1)">{comp.name}</span>
                  </div>
                </td>
                <td className="border-b border-(--line-2) px-4 py-[13px] text-end align-middle font-(family-name:--disp) text-[16px] font-extrabold tracking-[-0.01em] text-(--t-1)">
                  {named ? (
                    <span className="font-(family-name:--body-font) text-[12px] font-normal text-(--t-3)">
                      -
                    </span>
                  ) : (
                    comp.aeo_score
                  )}
                </td>
                <td className="border-b border-(--line-2) px-4 py-[13px] text-end align-middle font-(family-name:--disp) text-[16px] font-extrabold tracking-[-0.01em] text-(--t-1)">
                  {named ? (
                    <span className="font-(family-name:--body-font) text-[12px] font-normal text-(--t-3)">
                      -
                    </span>
                  ) : (
                    comp.score
                  )}
                </td>
                <td className="border-b border-(--line-2) px-4 py-[13px] text-end align-middle">
                  {named ? (
                    <span className="text-[12px] text-(--t-3)">
                      {t("signalAuditReport.competitors.notMeasured")}
                    </span>
                  ) : (
                    <span className="flex items-center justify-end gap-2.5">
                      <span className="h-1.5 w-[70px] overflow-hidden rounded-full bg-(--line)">
                        <span
                          className="block h-full rounded-full bg-(--purple)"
                          style={{ width: `${Math.min(100, Math.max(0, share))}%` }}
                        />
                      </span>
                      <b className="font-(family-name:--disp) text-[13px] font-bold text-(--t-1)">
                        {comp.geo_visibility}
                      </b>
                    </span>
                  )}
                </td>
                <td className="border-b border-(--line-2) px-[22px] py-[13px] text-end align-middle">
                  <span
                    className="font-(family-name:--mono) text-[11px] text-(--t-2)"
                    title={named ? t("signalAuditReport.competitors.discoveryNote") : undefined}
                  >
                    {t(`signalAuditReport.competitors.${key}`)}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
