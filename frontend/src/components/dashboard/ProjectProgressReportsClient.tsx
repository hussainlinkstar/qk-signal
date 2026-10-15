"use client";

import React, { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import {
  AlertTriangle,
  CalendarRange,
  Languages,
  Loader2,
  Mail,
  MessageSquareMore,
  RefreshCcw,
} from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import AuditAnnotationThread from "@/components/dashboard/AuditAnnotationThread";
import { cx } from "@/components/ui/utils";
import { useProjectLatestAudit } from "@/hooks/useProjectLatestAudit";
import { formatDateTime } from "@/lib/dateFormat";
import { extractAuditAnnotationTargets } from "@/lib/auditAnnotationTargets";
import { getReportLanguageLabel } from "@/lib/reportLanguages";
import {
  fetchProjectProgressReports,
  generateProjectProgressReport,
  type ProjectProgressReport,
} from "@/services/workspaceService";

type ReportSnapshot = {
  highlights?: string[];
  remaining_issues?: string[];
  current_scores?: Record<string, number | null>;
  previous_scores?: Record<string, number | null>;
  delta?: Record<string, number | null>;
  project?: {
    name?: string;
    domain_url?: string | null;
  };
};

const getSnapshot = (report: ProjectProgressReport | null): ReportSnapshot => {
  if (!report || typeof report.snapshot !== "object" || report.snapshot === null) {
    return {};
  }
  return report.snapshot as ReportSnapshot;
};

const formatMonthLabel = (value: string) => {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
  });
};

const listButtonClass = (selected: boolean) =>
  cx(
    "w-full rounded-(--r-md) border p-4 text-left transition",
    selected
      ? "border-(--purple) bg-(--purple-s)"
      : "border-(--line) bg-(--paper) hover:border-(--t-3)"
  );

export default function ProjectProgressReportsClient() {
  const params = useParams<{ projectId: string }>();
  const projectId = params?.projectId ?? "";
  const { getToken, isSignedIn } = useAuth();
  const { latestAudit } = useProjectLatestAudit(String(projectId));

  const [reports, setReports] = useState<ProjectProgressReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedReportId, setSelectedReportId] = useState<number | null>(null);
  const [busyAction, setBusyAction] = useState<"preview" | "email" | null>(null);
  const [selectedSectionPath, setSelectedSectionPath] = useState<string | null>(null);

  const getAuthHeaders = React.useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, [getToken]);

  const loadReports = React.useCallback(async () => {
    if (!projectId || !isSignedIn) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      const reportHistory = await fetchProjectProgressReports(projectId, headers);
      setReports(reportHistory);
      setSelectedReportId((current) => current ?? reportHistory[0]?.id ?? null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load report history.");
    } finally {
      setLoading(false);
    }
  }, [getAuthHeaders, isSignedIn, projectId]);

  useEffect(() => {
    void loadReports();
  }, [loadReports]);

  const handleGenerate = async (deliverEmail: boolean) => {
    if (!projectId) {
      return;
    }

    setBusyAction(deliverEmail ? "email" : "preview");
    setError(null);
    try {
      const headers = await getAuthHeaders();
      const created = await generateProjectProgressReport(
        projectId,
        { deliver_email: deliverEmail },
        headers
      );
      setReports((current) => {
        const next = [created, ...current.filter((item) => item.id !== created.id)];
        return next.sort((left, right) => right.report_month.localeCompare(left.report_month));
      });
      setSelectedReportId(created.id);
    } catch (actionError) {
      setError(
        actionError instanceof Error ? actionError.message : "Unable to generate progress report."
      );
    } finally {
      setBusyAction(null);
    }
  };

  const selectedReport = useMemo(
    () => reports.find((report) => report.id === selectedReportId) ?? reports[0] ?? null,
    [reports, selectedReportId]
  );
  const annotationTargets = useMemo(
    () =>
      extractAuditAnnotationTargets(
        latestAudit?.full_report as Record<string, unknown> | null | undefined
      ),
    [latestAudit?.full_report]
  );
  const selectedAnnotationTarget = useMemo(
    () =>
      annotationTargets.find((target) => target.sectionPath === selectedSectionPath) ??
      annotationTargets[0] ??
      null,
    [annotationTargets, selectedSectionPath]
  );
  const snapshot = getSnapshot(selectedReport);
  const highlights = Array.isArray(snapshot.highlights) ? snapshot.highlights : [];
  const remainingIssues = Array.isArray(snapshot.remaining_issues) ? snapshot.remaining_issues : [];

  useEffect(() => {
    if (!selectedSectionPath && annotationTargets.length > 0) {
      setSelectedSectionPath(annotationTargets[0].sectionPath);
      return;
    }
    if (
      selectedSectionPath &&
      annotationTargets.length > 0 &&
      !annotationTargets.some((target) => target.sectionPath === selectedSectionPath)
    ) {
      setSelectedSectionPath(annotationTargets[0].sectionPath);
    }
  }, [annotationTargets, selectedSectionPath]);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12">
        <div className="flex items-center gap-3 text-sm font-medium text-(--t-2)">
          <Loader2 className="h-4 w-4 animate-spin text-(--purple)" />
          Loading report history...
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <section className="rounded-[22px] border-0 bg-white px-6 py-[22px]">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="m-0 font-(family-name:--mono) text-[11px] uppercase tracking-[0.14em] text-(--purple)">
              Automated Progress Reports
            </p>
            <h3 className="m-0 mt-1.5 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
              Monthly proof packs for client retention
            </h3>
            <p className="m-0 mt-1 text-[12.5px] leading-[1.5] text-(--t-3)">
              Generate an on-demand preview, trigger a branded email delivery, or review the
              snapshot history stored for this project.
            </p>
          </div>

          <div className="flex flex-none flex-wrap items-center gap-3 max-md:w-full">
            <button
              type="button"
              className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3] max-md:min-h-11"
              onClick={() => handleGenerate(false)}
              disabled={busyAction !== null}
            >
              {busyAction === "preview" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCcw className="h-4 w-4" />
              )}
              <span>Generate Preview</span>
            </button>
            <button
              type="button"
              className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black max-md:min-h-11"
              onClick={() => handleGenerate(true)}
              disabled={busyAction !== null}
            >
              {busyAction === "email" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Mail className="h-4 w-4" />
              )}
              <span>Generate + Email</span>
            </button>
          </div>
        </div>

        {error ? <p className="mt-4 text-sm font-medium text-(--bad)">{error}</p> : null}
      </section>

      {reports.length === 0 ? (
        <section className="rounded-[22px] border-0 bg-white px-6 py-[22px] text-center">
          <CalendarRange className="mx-auto h-10 w-10 text-(--t-3)" />
          <h4 className="m-0 mt-3 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
            No monthly reports yet
          </h4>
          <p className="m-0 mx-auto mt-1.5 max-w-lg text-[12.5px] leading-[1.5] text-(--t-3)">
            Generate the first progress report after the project has at least one audit. When the
            previous month has no audits yet, preview generation uses the latest assessmented month.
            Every report is stored as a frozen snapshot so client-facing history stays intact.
          </p>
        </section>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
          <section className="rounded-[22px] border-0 bg-white px-6 py-[22px]">
            <div className="space-y-3">
              {reports.map((report) => (
                <button
                  key={report.id}
                  type="button"
                  onClick={() => setSelectedReportId(report.id)}
                  className={listButtonClass(selectedReport?.id === report.id)}
                >
                  <p className="m-0 font-(family-name:--mono) text-[11px] uppercase tracking-[0.14em] text-(--t-3)">
                    {formatMonthLabel(report.report_month)}
                  </p>
                  <p className="mt-2 text-sm font-semibold text-(--t-1)">
                    {report.generated_by === "automation" ? "Automated cycle" : "Manual snapshot"}
                  </p>
                  <div
                    className="rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] mt-3"
                    aria-label={`Report language ${getReportLanguageLabel(report.language)}`}
                  >
                    <Languages className="h-3.5 w-3.5" />
                    <span>{getReportLanguageLabel(report.language)}</span>
                  </div>
                  {report.expired ? (
                    <div
                      className="rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] mt-2 border-[color-mix(in_srgb,var(--warn)_35%,transparent)] bg-[color-mix(in_srgb,var(--warn)_8%,var(--panel))] text-(--warn)"
                      title={`Removed after ${report.retention_days} days per retention policy.`}
                    >
                      <AlertTriangle className="h-3 w-3" />
                      <span>Report expired</span>
                    </div>
                  ) : null}
                  <p className="mt-2 text-xs text-(--t-3)">
                    {report.recipient_count} recipients
                    {report.email_sent_at
                      ? ` - emailed ${formatDateTime(report.email_sent_at)}`
                      : " - preview only"}
                  </p>
                </button>
              ))}
            </div>
          </section>

          <section className="rounded-[22px] border-0 bg-white px-6 py-[22px]">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="m-0 font-(family-name:--mono) text-[11px] uppercase tracking-[0.14em] text-(--t-3)">
                  Report Snapshot
                </p>
                <h4 className="m-0 mt-1.5 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
                  {selectedReport
                    ? formatMonthLabel(selectedReport.report_month)
                    : "Select a report"}
                </h4>
                {selectedReport ? (
                  <div
                    className="rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] mt-3 border-[color-mix(in_srgb,var(--purple)_30%,transparent)] bg-(--purple-s) text-(--purple)"
                    aria-label={`Report language ${getReportLanguageLabel(selectedReport.language)}`}
                  >
                    <Languages className="h-3.5 w-3.5" />
                    <span>{getReportLanguageLabel(selectedReport.language)}</span>
                  </div>
                ) : null}
                {selectedReport?.expired ? (
                  <div
                    className="rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] mt-3 border-[color-mix(in_srgb,var(--warn)_35%,transparent)] bg-[color-mix(in_srgb,var(--warn)_8%,var(--panel))] text-(--warn)"
                    title={`Removed after ${selectedReport.retention_days} days per retention policy.`}
                  >
                    <AlertTriangle className="h-3.5 w-3.5" />
                    <span>Report expired</span>
                  </div>
                ) : null}
                <p className="mt-2 text-sm text-(--t-2)">
                  {snapshot.project?.name ?? "Monthly performance snapshot"}
                  {snapshot.project?.domain_url ? ` - ${snapshot.project.domain_url}` : ""}
                </p>
              </div>
              {selectedReport?.created_at ? (
                <p className="text-xs text-(--t-3)">
                  Generated {formatDateTime(selectedReport.created_at)}
                </p>
              ) : null}
            </div>

            <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              {[
                {
                  label: "SEO",
                  current: snapshot.current_scores?.seo ?? null,
                  delta: snapshot.delta?.seo ?? null,
                },
                {
                  label: "AI visibility",
                  current: snapshot.current_scores?.geo ?? null,
                  delta: snapshot.delta?.geo ?? null,
                },
                {
                  label: "AI answers",
                  current: snapshot.current_scores?.aeo ?? null,
                  delta: snapshot.delta?.aeo ?? null,
                },
                {
                  label: "Overall",
                  current: snapshot.current_scores?.overall ?? null,
                  delta: snapshot.delta?.overall ?? null,
                },
              ].map((metric) => (
                <div
                  key={metric.label}
                  className="rounded-(--r-md) border-0 bg-[#EEF1F6] p-5"
                >
                  <p className="m-0 font-(family-name:--mono) text-[11px] uppercase tracking-[0.14em] text-(--t-3)">
                    {metric.label}
                  </p>
                  <p className="mt-3 font-(family-name:--disp) text-[28px] font-bold leading-none tracking-[-0.02em] text-(--t-1)">
                    {typeof metric.current === "number" ? Math.round(metric.current) : "--"}
                  </p>
                  <p
                    className="mt-3 text-xs font-medium text-(--metric-delta)"
                    style={
                      {
                        "--metric-delta":
                          typeof metric.delta !== "number"
                            ? "var(--t-3)"
                            : metric.delta >= 0
                              ? "var(--good)"
                              : "var(--bad)",
                      } as React.CSSProperties
                    }
                  >
                    {typeof metric.delta === "number"
                      ? `${metric.delta >= 0 ? "+" : ""}${Math.round(metric.delta * 10) / 10} vs previous month`
                      : "No prior period"}
                  </p>
                </div>
              ))}
            </div>

            <div className="mt-6 grid gap-6 xl:grid-cols-2">
              <div className="rounded-(--r-md) border-0 bg-[#EEF1F6] p-5">
                <p className="m-0 font-(family-name:--mono) text-[11px] uppercase tracking-[0.14em] text-(--good)">
                  Top improvements
                </p>
                <ul className="mt-4 space-y-3 text-sm leading-7 text-(--t-2)">
                  {highlights.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                  {highlights.length === 0 ? (
                    <li className="text-(--t-3)">No highlights captured for this snapshot.</li>
                  ) : null}
                </ul>
              </div>

              <div className="rounded-(--r-md) border-0 bg-[#EEF1F6] p-5">
                <p className="m-0 font-(family-name:--mono) text-[11px] uppercase tracking-[0.14em] text-(--warn)">
                  Remaining issues
                </p>
                <ul className="mt-4 space-y-3 text-sm leading-7 text-(--t-2)">
                  {remainingIssues.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                  {remainingIssues.length === 0 ? (
                    <li className="text-(--t-3)">
                      No unresolved issues captured for this snapshot.
                    </li>
                  ) : null}
                </ul>
              </div>
            </div>
          </section>
        </div>
      )}

      <section className="rounded-[22px] border-0 bg-white px-6 py-[22px]">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-(--line) pb-5">
          <div className="min-w-0">
            <p className="m-0 font-(family-name:--mono) text-[11px] uppercase tracking-[0.14em] text-(--purple)">
              Living Report Context
            </p>
            <h3 className="m-0 mt-1.5 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
              Annotate the latest assessment before it reaches the client
            </h3>
            <p className="m-0 mt-1 text-[12.5px] leading-[1.5] text-(--t-3)">
              Add internal delivery notes, publish client-visible context, and keep replies attached
              directly to the recommendation that needs discussion.
            </p>
          </div>
          {latestAudit?.created_at ? (
            <p className="text-xs text-(--t-3)">
              Latest audit {formatDateTime(latestAudit.created_at)}
            </p>
          ) : null}
        </div>

        {!latestAudit ? (
          <div className="mt-6 rounded-(--r-md) border border-dashed border-(--line) bg-(--paper) p-6 text-sm leading-7 text-(--t-2)">
            Run a fresh project audit to unlock recommendation-level annotations and client reply
            threads.
          </div>
        ) : annotationTargets.length === 0 ? (
          <div className="mt-6 rounded-(--r-md) border border-dashed border-(--line) bg-(--paper) p-6">
            <div className="flex items-start gap-3">
              <MessageSquareMore className="mt-0.5 h-5 w-5 text-(--t-3)" />
              <div>
                <p className="text-sm font-semibold text-(--t-1)">No annotation targets found</p>
                <p className="mt-2 text-sm leading-7 text-(--t-2)">
                  This audit does not expose recommendation blocks yet, so annotation threads are
                  not available for this report version.
                </p>
              </div>
            </div>
          </div>
        ) : (
          <div className="mt-6 grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
            <div className="space-y-3">
              {annotationTargets.map((target) => (
                <button
                  key={target.sectionPath}
                  type="button"
                  onClick={() => setSelectedSectionPath(target.sectionPath)}
                  className={listButtonClass(
                    selectedAnnotationTarget?.sectionPath === target.sectionPath
                  )}
                >
                  <p className="m-0 font-(family-name:--mono) text-[11px] uppercase tracking-[0.14em] text-(--t-3)">
                    {target.category}
                  </p>
                  <p className="mt-2 text-sm font-semibold text-(--t-1)">{target.title}</p>
                  {target.description ? (
                    <p className="mt-2 text-xs leading-6 text-(--t-2)">{target.description}</p>
                  ) : null}
                </button>
              ))}
            </div>

            {selectedAnnotationTarget ? (
              <AuditAnnotationThread
                auditId={latestAudit.id}
                sectionPath={selectedAnnotationTarget.sectionPath}
                sourceRecommendationKey={selectedAnnotationTarget.sourceRecommendationKey}
                title={selectedAnnotationTarget.title}
                description={selectedAnnotationTarget.description}
              />
            ) : null}
          </div>
        )}
      </section>
    </div>
  );
}
