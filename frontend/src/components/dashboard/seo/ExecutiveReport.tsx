"use client";

import React, { useMemo } from "react";
import { Download, Printer } from "lucide-react";
import AiDisclaimer from "@/components/ui/AiDisclaimer";
import Card from "@/components/ui/Card";
import { renderElementToPdf } from "@/lib/pdfExport";
import type { AiStrategistViewModel, ScoreKey } from "@/types/aiStrategist";
import { calculateDelta, sortPriorityActions } from "@/utils/seoCalculations";
import { formatDateTime } from "@/lib/dateFormat";

type ExecutiveReportProps = {
  latest: AiStrategistViewModel;
  history: AiStrategistViewModel[];
  generatedAt?: string;
};

type MetricConfig = {
  key: ScoreKey;
  label: string;
};

const SCORE_METRICS: MetricConfig[] = [
  { key: "seo", label: "SEO" },
  { key: "speed", label: "Speed" },
  { key: "indexing", label: "Indexing" },
  { key: "mobile", label: "Mobile" },
];

const buildSeoTrend = (history: AiStrategistViewModel[]) =>
  history.map((entry) => ({
    date: entry.createdAt,
    value: entry.scores.seo,
  }));

const formatDateForFilename = (value = new Date()): string => {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};

const getDomainFromUrl = (siteUrl?: string): string => {
  if (!siteUrl) {
    return "site";
  }

  try {
    const normalized = siteUrl.startsWith("http") ? siteUrl : `https://${siteUrl}`;
    const hostname = new URL(normalized).hostname.replace(/^www\./, "");
    return hostname || "site";
  } catch {
    return (
      siteUrl
        .replace(/^https?:\/\//, "")
        .replace(/^www\./, "")
        .split("/")[0] || "site"
    );
  }
};

const trendToneMap = {
  up: "text-emerald-300",
  down: "text-rose-300",
  flat: "text-(--t-2)",
} as const;

export default function ExecutiveReport({ latest, history, generatedAt }: ExecutiveReportProps) {
  const reportRef = React.useRef<HTMLDivElement | null>(null);
  const previousAudit = history.length >= 2 ? history[history.length - 2] : null;
  const analyzedDomain = useMemo(() => getDomainFromUrl(latest.siteUrl), [latest.siteUrl]);

  const issueSummary = useMemo(() => {
    const categories = [...latest.issueCategories]
      .filter((category) => category.count > 0)
      .sort((a, b) => b.count - a.count);

    const total = categories.reduce((sum, category) => sum + category.count, 0);

    return {
      total,
      topCategories: categories.slice(0, 3),
    };
  }, [latest.issueCategories]);

  const topPriorityActions = useMemo(
    () => sortPriorityActions(latest.priorityActions).slice(0, 5),
    [latest.priorityActions]
  );

  const seoTrend = useMemo(() => buildSeoTrend(history), [history]);

  const trendSummary = useMemo(() => {
    if (seoTrend.length === 0) {
      return null;
    }

    const current = seoTrend[seoTrend.length - 1]?.value ?? 0;
    const previous = seoTrend.length >= 2 ? seoTrend[seoTrend.length - 2]?.value : undefined;
    const delta = calculateDelta(current, previous);

    return {
      current,
      previous,
      delta,
    };
  }, [seoTrend]);

  const handlePrintPdf = () => {
    window.print();
  };

  const handleDownloadPdf = () => {
    const reportElement = reportRef.current;
    if (!reportElement) return;

    const date = formatDateForFilename(new Date());

    void renderElementToPdf({
      element: reportElement,
      reportTitle: "Executive Report",
      subtitleLines: [`Site: ${latest.siteUrl || "N/A"}`],
      fileName: `Executive-Report-${analyzedDomain}-${date}.pdf`,
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-end gap-2 print:hidden">
        <button
          type="button"
          onClick={handlePrintPdf}
          className="inline-flex items-center gap-2 rounded-xl border border-(--line) bg-(--line-2) px-3 py-2 text-sm font-medium text-(--t-1) transition-colors hover:bg-(--line-2)"
        >
          <Printer className="h-4 w-4" aria-hidden="true" />
          Print / Save as PDF
        </button>
        <button
          type="button"
          onClick={handleDownloadPdf}
          className="inline-flex items-center gap-2 rounded-lg bg-thoth-logic px-3 py-2 text-sm font-semibold text-(--t-1) transition-colors hover:bg-blue-700"
        >
          <Download className="h-4 w-4" aria-hidden="true" />
          Export PDF
        </button>
      </div>

      <div ref={reportRef}>
        <Card className="executive-report-print space-y-6 p-6 print:block print:space-y-4 print:rounded-none print:border-0 md:p-8">
          <section className="space-y-4 break-inside-avoid">
            <h2 className="text-xl font-bold text-thoth-logic">Executive Header</h2>
            <div className="grid gap-4 md:grid-cols-3">
              <div className="rounded border border-(--line) bg-(--line-2) p-5 shadow-inner">
                <p className="text-xs font-bold tracking-widest uppercase text-(--t-2)">Title</p>
                <p className="mt-2 text-lg font-bold text-(--t-1)">Executive Report</p>
              </div>
              <div className="rounded border border-(--line) bg-(--line-2) p-5 shadow-inner">
                <p className="text-xs font-bold tracking-widest uppercase text-(--t-2)">
                  Generation date
                </p>
                <p className="mt-2 text-sm font-semibold text-(--t-1)">
                  {formatDateTime(generatedAt ?? latest.createdAt)}
                </p>
              </div>
              <div className="rounded border border-(--line) bg-(--line-2) p-5 shadow-inner">
                <p className="text-xs font-bold tracking-widest uppercase text-(--t-2)">
                  Domeniu/site analizat
                </p>
                <p className="mt-2 text-sm font-semibold text-(--t-1)">
                  {latest.siteUrl || analyzedDomain}
                </p>
                <p className="text-xs text-(--t-2)">Domain: {analyzedDomain}</p>
              </div>
            </div>
            <p className="hidden text-sm text-(--t-3) print:block">
              Raport generat: {formatDateTime(generatedAt ?? latest.createdAt)} • Site:{" "}
              {latest.siteUrl || "-"}
            </p>
          </section>

          <section className="space-y-3 break-inside-avoid">
            <h2 className="text-xl font-bold text-thoth-logic">Scores &amp; Delta</h2>
            <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {SCORE_METRICS.map(({ key, label }) => {
                const current = latest.scores[key];
                const previous = previousAudit?.scores[key];
                const rawDelta = latest.scoreDeltaVsPrevious[key];
                const numericDelta = Number.isFinite(rawDelta)
                  ? Number(rawDelta)
                  : Number.isFinite(previous)
                    ? current - Number(previous)
                    : null;
                const delta = calculateDelta(current, previous);

                return (
                  <div
                    key={key}
                    className="break-inside-avoid rounded border border-(--line) bg-(--line-2) p-4 shadow-inner"
                  >
                    <dt className="text-sm text-(--t-2)">{label}</dt>
                    <dd className="mt-1 text-xl font-semibold text-(--t-1)">{current}</dd>
                    <p className="mt-1 text-xs text-(--t-2)">
                      Δ pts:{" "}
                      {numericDelta === null
                        ? ", "
                        : `${numericDelta > 0 ? "+" : ""}${numericDelta}`}
                    </p>
                    <p className={`text-xs ${trendToneMap[delta.trend]}`}>
                      {delta.hasEnoughData
                        ? `${delta.trendSymbol} ${delta.percentage}% vs previous audit`
                        : "Trend indisponibil"}
                    </p>
                  </div>
                );
              })}
            </dl>
          </section>

          <section className="space-y-2 break-inside-avoid">
            <h2 className="text-xl font-bold text-thoth-logic">Trend Summary</h2>
            {trendSummary ? (
              <p className="text-sm text-(--t-2)">
                The latest SEO score is{" "}
                <span className="font-semibold text-(--t-1)">{trendSummary.current}</span>
                {trendSummary.delta.hasEnoughData
                  ? `, change ${trendSummary.delta.trendSymbol} ${trendSummary.delta.percentage}% vs the previous audit, trend ${trendSummary.delta.trend}.`
                  : ", trend unavailable (insufficient assessments)."}
              </p>
            ) : (
              <p className="text-sm text-(--t-2)">
                No historical data is available for the trend summary.
              </p>
            )}
          </section>

          <section className="space-y-3 break-inside-avoid">
            <h2 className="text-xl font-bold text-thoth-logic">Issue Distribution</h2>
            <p className="text-sm text-(--t-2)">Total issues: {issueSummary.total}</p>
            {issueSummary.topCategories.length > 0 ? (
              <ul className="space-y-2 text-sm text-(--t-1) break-inside-avoid">
                {issueSummary.topCategories.map((category) => (
                  <li
                    key={category.key}
                    className="break-inside-avoid flex items-center justify-between rounded-xl border border-(--line) bg-(--line-2) px-4 py-3"
                  >
                    <span>{category.label}</span>
                    <span className="font-semibold text-(--t-1)">{category.count}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-(--t-2)">No issue categories are available.</p>
            )}
          </section>

          <section className="space-y-3 break-inside-avoid">
            <h2 className="text-xl font-bold text-thoth-logic">Top Priority Actions</h2>
            {topPriorityActions.length > 0 ? (
              <ol className="space-y-2 text-sm text-(--t-1) break-inside-avoid">
                {topPriorityActions.map((action) => (
                  <li
                    key={action.id}
                    className="break-inside-avoid rounded-xl border border-(--line) bg-(--line-2) px-4 py-3"
                  >
                    <p className="font-semibold text-(--t-1)">{action.title}</p>
                    <p className="text-xs text-(--t-2)">
                      Priority {action.priority} • Impact {action.impact} • Effort {action.effort}
                    </p>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-sm text-(--t-2)">
                No priority actions are available for this audit.
              </p>
            )}
          </section>

          <section className="space-y-4 break-inside-avoid page-break-before">
            <h2 className="text-xl font-bold text-thoth-logic">AI Strategic Insights</h2>
            <div className="space-y-3 rounded-xl border border-emerald-400/30 bg-emerald-500/10 p-4 text-sm text-emerald-50 break-inside-avoid">
              <h3 className="font-semibold text-emerald-100">Executive summary</h3>
              <p>{latest.aiInsights.executive_summary || "-"}</p>
            </div>

            <div>
              <h3 className="mb-2 text-sm font-semibold text-(--t-1)">Critical alerts</h3>
              <ul className="space-y-2 text-sm text-(--t-1) break-inside-avoid">
                {latest.aiInsights.critical_alerts.length > 0 ? (
                  latest.aiInsights.critical_alerts.map((alert, index) => (
                    <li
                      key={`critical-alert-${index + 1}`}
                      className="break-inside-avoid rounded-xl border border-(--line) bg-(--line-2) px-4 py-3"
                    >
                      {alert}
                    </li>
                  ))
                ) : (
                  <li className="rounded-md border border-(--line) px-3 py-2 text-(--t-2)">-</li>
                )}
              </ul>
            </div>

            <div>
              <h3 className="mb-2 text-sm font-semibold text-(--t-1)">Priority roadmap</h3>
              <ul className="space-y-2 text-sm text-(--t-1) break-inside-avoid">
                {latest.aiInsights.priority_roadmap.length > 0 ? (
                  latest.aiInsights.priority_roadmap.map((item, index) => (
                    <li
                      key={`roadmap-${index + 1}`}
                      className="break-inside-avoid rounded-xl border border-(--line) bg-(--line-2) px-4 py-3"
                    >
                      <p className="font-semibold text-(--t-1)">{item.task}</p>
                      <p className="text-xs text-(--t-2)">
                        Category: {item.category} • Impact: {item.impact} • Effort score:{" "}
                        {item.effort_score}
                      </p>
                      <p className="mt-1 text-xs text-(--t-2)">{item.reasoning}</p>
                    </li>
                  ))
                ) : (
                  <li className="rounded-md border border-(--line) px-3 py-2 text-(--t-2)">-</li>
                )}
              </ul>
            </div>

            <div>
              <h3 className="mb-2 text-sm font-semibold text-(--t-1)">Content gap theory</h3>
              <ul className="space-y-2 text-sm text-(--t-1) break-inside-avoid">
                {latest.aiInsights.content_gap_theory.length > 0 ? (
                  latest.aiInsights.content_gap_theory.map((item, index) => (
                    <li
                      key={`content-gap-${index + 1}`}
                      className="break-inside-avoid rounded-xl border border-(--line) bg-(--line-2) px-4 py-3"
                    >
                      {item}
                    </li>
                  ))
                ) : (
                  <li className="rounded-md border border-(--line) px-3 py-2 text-(--t-2)">-</li>
                )}
              </ul>
            </div>

            <div className="rounded border border-(--line) bg-(--line-2) p-5 shadow-inner">
              <h3 className="mb-1 text-sm font-semibold text-(--t-1)">
                Technical debt explanation
              </h3>
              <p className="text-sm text-(--t-2)">
                {latest.aiInsights.technical_debt_explanation || "-"}
              </p>
            </div>
            <AiDisclaimer className="print:border-slate-300/40 print:bg-transparent" />
          </section>
        </Card>
      </div>
    </div>
  );
}
