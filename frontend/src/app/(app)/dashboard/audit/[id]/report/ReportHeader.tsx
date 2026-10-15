"use client";

import React from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { ArrowLeft, Globe } from "lucide-react";

import { ClientSafeDate } from "@/lib/dateFormat";
import { getTierShort } from "@/constants/tiers";
import ScoreDeltaBadge from "@/components/results/ScoreDeltaBadge";
import ScoreRing from "./ScoreRing";
import { ScheduleAutomation } from "@/components/results/ScheduleAutomation";
import SignalExportMenu from "@/components/signal/SignalExportMenu";
import type { ScoreDelta } from "@/hooks/useAuditComparison";

export default function ReportHeader({
  url,
  auditId,
  numericAuditId,
  auditType,
  createdAt,
  overallScore,
  overallDelta,
  previousAuditDate,
  scheduleParams,
  projectId,
  onBack,
}: {
  url: string;
  auditId: string;
  numericAuditId: number | null;
  auditType?: string | null;
  createdAt?: string | null;
  overallScore: number | null;
  overallDelta?: ScoreDelta;
  previousAuditDate?: string | null;
  scheduleParams: Record<string, unknown>;
  projectId?: number | null;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const host = url.replace(/^https?:\/\/(www\.)?/, "");

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onBack}
          aria-label={t("signalAuditReport.header.back")}
          className="flex h-9 w-9 items-center justify-center rounded-[14px] border-0 bg-[#EEF1F6] text-(--text-muted) transition-colors hover:text-(--foreground)"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div className="flex gap-2 font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--text-muted)">
          <Link
            href="/dashboard/audit"
            className="transition-colors hover:text-(--foreground) max-md:inline-flex max-md:min-h-11 max-md:items-center"
          >
            {t("signalAuditReport.header.checks")}
          </Link>
          <span>/</span>
          <span className="text-(--foreground)">{t("signalAuditReport.header.report")}</span>
        </div>
      </div>

      <div className="rounded-[22px] border-0 bg-white">
        <div className="flex flex-col gap-4 px-5 py-4 md:px-6 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex min-w-0 flex-1 items-center gap-4">
            <div className="flex shrink-0 flex-col items-center gap-1">
              <ScoreRing
                value={overallScore}
                size={76}
                label={t("signalAuditReport.header.overall")}
              />
              <span className="font-(family-name:--mono) text-[10px] uppercase tracking-[0.08em] text-(--t-3)">
                {t("signalAuditReport.header.overall")}
              </span>
              {overallDelta?.delta != null ? (
                <ScoreDeltaBadge
                  delta={overallDelta.delta}
                  direction={overallDelta.direction}
                  previousScore={overallDelta.previous}
                  previousDate={
                    previousAuditDate ? new Date(previousAuditDate).toLocaleDateString() : null
                  }
                  size="sm"
                />
              ) : null}
            </div>
            <div className="min-w-0">
              <div className="font-(family-name:--mono) text-[11px] uppercase tracking-[0.14em] text-(--purple)">
                {t("signalAuditReport.header.eyebrow")}
              </div>
              <h1
                className="mt-1 mb-1 flex items-center gap-3 font-(family-name:--disp) text-[28px] font-black lowercase tracking-[-0.02em]"
                title={url}
              >
                <span className="truncate">{host}</span>
                <a
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={t("signalAuditReport.header.openSite")}
                  className="flex h-6 w-6 shrink-0 items-center justify-center rounded border-0 bg-(--background) text-(--text-muted) transition-colors hover:border-primary/30 hover:text-primary"
                >
                  <Globe className="h-3.5 w-3.5" />
                </a>
              </h1>
              <p className="m-0 text-[13.5px] leading-[1.55] text-(--t-2)">
                {t("signalAuditReport.header.meta", {
                  id: auditId.slice(0, 8),
                  tier: auditType ? getTierShort(auditType) : "",
                })}
                {" · "}
                <ClientSafeDate date={createdAt} />
              </p>
            </div>
          </div>

          <div className="flex min-w-0 flex-1 flex-col items-stretch gap-3 lg:flex-row lg:items-center">
            <div className="flex min-w-0 flex-1 flex-col gap-3 sm:flex-row sm:items-center">
              <ScheduleAutomation
                targetUrl={url}
                isLocked={false}
                projectId={projectId ?? null}
                auditParams={scheduleParams}
                variant="compact"
                compactLockedMode="strip"
                className="min-w-0 w-full flex-1"
              />
              <SignalExportMenu
                page="report"
                reportKind="standard"
                auditId={numericAuditId}
                projectId={projectId ?? null}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
