"use client";

import { BASE_PATH } from "@/lib/basePath";
import React, { useCallback, useMemo, useState } from "react";
import {
  Copy,
  Download,
  FileJson,
  FileText,
  Link2,
  Loader2,
  Settings2,
  Shield,
} from "lucide-react";
import type { CanonicalAuditReport } from "@/lib/reportAdapters";
import type { AuditHistoryItem } from "@/types/auditWorkspace";
import {
  generateAuditPdfReport,
  DEFAULT_SECTIONS,
  type ReportSections,
} from "@/lib/generateAuditPdfReport";
import { cx } from "@/components/ui/utils";

type ExportTabProps = {
  handleCopySummary: () => void;
  handleExportJson: () => void;
  copyStatus: string;
  activeReport: CanonicalAuditReport | null;
  activeAuditMeta: AuditHistoryItem | null;
  getAuthHeaders?: () => Promise<Record<string, string>>;
};

const hasObjectContent = (value: unknown): boolean =>
  typeof value === "object" &&
  value !== null &&
  Object.keys(value as Record<string, unknown>).length > 0;

const hasArrayContent = (value: unknown): boolean => Array.isArray(value) && value.length > 0;

const SECTION_LABELS: { key: keyof ReportSections; label: string; description: string }[] = [
  {
    key: "seo",
    label: "SEO overview",
    description: "Search visibility, site health, and Core Web Vitals",
  },
  {
    key: "aeo",
    label: "AI answers insights",
    description: "Answer visibility, snippets, and entity clarity",
  },
  {
    key: "geo",
    label: "AI visibility insights",
    description: "AI search presence, citations, and trust signals",
  },
  {
    key: "technical",
    label: "Technical metrics",
    description: "Performance, delivery, and Core Web Vitals",
  },
  {
    key: "ai",
    label: "AI insights",
    description: "Executive summary, findings, and strategic notes",
  },
  {
    key: "competitors",
    label: "Competitor analysis",
    description: "Benchmarks and market comparison data",
  },
];

export default function ExportTab({
  handleCopySummary,
  handleExportJson,
  copyStatus,
  activeReport,
  activeAuditMeta,
  getAuthHeaders,
}: ExportTabProps) {
  const [sections, setSections] = useState<ReportSections>({ ...DEFAULT_SECTIONS });
  const [isGeneratingPdf, setIsGeneratingPdf] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const showTechnicalSection = useMemo(
    () =>
      hasObjectContent(activeReport?.performance) ||
      hasObjectContent(activeReport?.network) ||
      hasObjectContent(activeReport?.technical_signals),
    [activeReport]
  );

  const showAiSection = useMemo(
    () =>
      hasObjectContent(activeReport?.analysis) ||
      hasObjectContent(activeReport?.metadata) ||
      hasObjectContent(activeReport?.hallucination) ||
      hasObjectContent(activeReport?.integrity_certificate) ||
      hasArrayContent(activeReport?.intelligence_dossier) ||
      Boolean(activeReport?.executive_summary?.trim()) ||
      Boolean(activeReport?.strategic_summary?.trim()) ||
      Boolean(activeReport?.neural_executive_summary?.trim()),
    [activeReport]
  );

  const showCompetitorsSection = useMemo(
    () => hasArrayContent(activeReport?.competitors),
    [activeReport]
  );

  const visibleSectionLabels = useMemo(
    () =>
      SECTION_LABELS.filter(({ key }) => {
        if (key === "technical") return showTechnicalSection;
        if (key === "ai") return showAiSection;
        if (key === "competitors") return showCompetitorsSection;
        return true;
      }),
    [showAiSection, showCompetitorsSection, showTechnicalSection]
  );

  const exportSections = useMemo<ReportSections>(
    () => ({
      ...sections,
      technical: showTechnicalSection ? sections.technical : false,
      ai: showAiSection ? sections.ai : false,
      competitors: showCompetitorsSection ? sections.competitors : false,
    }),
    [sections, showAiSection, showCompetitorsSection, showTechnicalSection]
  );

  const enabledSectionCount = visibleSectionLabels.filter(({ key }) => exportSections[key]).length;

  const toggleSection = useCallback((key: keyof ReportSections) => {
    setSections((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  const handleDownloadReport = useCallback(async () => {
    if (!activeReport || !activeAuditMeta) return;
    setIsGeneratingPdf(true);
    try {
      await generateAuditPdfReport(activeReport, activeAuditMeta, exportSections);
    } catch (err) {
      console.error("PDF generation failed:", err);
    } finally {
      setIsGeneratingPdf(false);
    }
  }, [activeReport, activeAuditMeta, exportSections]);

  const [shareLinkCopied, setShareLinkCopied] = useState(false);

  const handleCopyShareLink = useCallback(async () => {
    if (!activeAuditMeta?.id || !getAuthHeaders) return;
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(`/api/audits/${activeAuditMeta.id}/share`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
      });
      if (!res.ok) return;
      const data = await res.json();
      const shareUrl = `${window.location.origin}${BASE_PATH}/share/${activeAuditMeta.id}?token=${data.share_token}`;
      await navigator.clipboard.writeText(shareUrl);
      setShareLinkCopied(true);
      setTimeout(() => setShareLinkCopied(false), 2500);
    } catch {
      /* clipboard API or network call may fail */
    }
  }, [activeAuditMeta?.id, getAuthHeaders]);

  const hasReport = !!activeReport && !!activeAuditMeta;

  return (
    <div className="space-y-12 pb-12">
      {/* Primary PDF Report */}
      <div className="relative group">
        <div className="relative flex flex-col items-center space-y-8 overflow-hidden text-center">
          <div className="relative z-10 max-w-xl space-y-4">
            <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded border border-primary/20 bg-primary/10 text-primary transition-transform duration-700 group-hover:scale-110">
              <FileText className="h-8 w-8" />
            </div>
            <h3 className="text-2xl font-black tracking-tight text-(--t-1)">Generate PDF report</h3>
            <p className="text-sm font-medium leading-relaxed text-(--t-2)">
              Create a clear, shareable report with your scores, charts, key findings, and
              recommended next steps.
            </p>
          </div>

          <div className="relative z-10 w-full max-w-2xl space-y-6">
            <button
              type="button"
              onClick={() => setShowSettings((prev) => !prev)}
              className="inline-flex items-center gap-3 rounded-xl border border-(--line) bg-(--panel) px-4 py-2 text-xs font-semibold text-(--t-2) transition-all hover:bg-(--line-2) hover:text-(--t-1)"
            >
              <Settings2 className="h-3.5 w-3.5" />
              Choose report sections
              <span className="ml-2 text-primary">
                ({enabledSectionCount}/{visibleSectionLabels.length})
              </span>
            </button>
            <p className="text-xs text-(--t-3)">The overview page is always included.</p>

            {showSettings && (
              <div className="grid gap-3 animate-in fade-in slide-in-from-top-4 duration-500 sm:grid-cols-2">
                {visibleSectionLabels.map(({ key, label, description }) => (
                  <label
                    key={key}
                    className={cx(
                      "flex cursor-pointer items-start gap-4 rounded border p-4 transition-all duration-300",
                      exportSections[key]
                        ? "border-primary/40 bg-primary/5"
                        : "border-(--line)  opacity-40 hover:opacity-60"
                    )}
                  >
                    <div className="relative flex items-center pt-0.5">
                      <input
                        type="checkbox"
                        checked={exportSections[key]}
                        onChange={() => toggleSection(key)}
                        className="sr-only"
                      />
                      <div
                        className={cx(
                          "flex h-5 w-5 items-center justify-center rounded-lg border transition-all",
                          exportSections[key]
                            ? "border-primary bg-primary"
                            : "border-(--line) bg-(--line-2)"
                        )}
                      >
                        {exportSections[key] && <div className="h-2 w-2 rounded-sm bg-black" />}
                      </div>
                    </div>
                    <div className="space-y-1 text-left">
                      <span className="text-sm font-semibold leading-none text-(--t-1)">
                        {label}
                      </span>
                      <p className="text-xs leading-tight text-(--t-2)">{description}</p>
                    </div>
                  </label>
                ))}
              </div>
            )}
          </div>

          <div className="relative z-10 flex w-full flex-col items-center gap-4 pt-4">
            <button
              type="button"
              onClick={handleDownloadReport}
              disabled={!hasReport || isGeneratingPdf}
              className={cx(
                "group/btn relative flex items-center justify-center gap-3 overflow-hidden rounded px-10 py-5 text-[11px] font-black uppercase tracking-[0.08em] transition-all duration-500",
                hasReport && !isGeneratingPdf
                  ? "bg-primary text-white hover:-translate-y-0.5 hover:shadow-[0_0_30px_rgba(6,182,212,0.6)] active:translate-y-0"
                  : "cursor-not-allowed border border-(--line) bg-(--panel) text-(--t-3)"
              )}
            >
              {isGeneratingPdf ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Preparing PDF...
                </>
              ) : (
                <>
                  <Download className="h-4 w-4 transition-transform group-hover/btn:scale-110" />
                  Download PDF
                </>
              )}
            </button>

            {!hasReport && (
              <p className="text-xs text-(--t-3)">Select or run an audit to enable PDF export.</p>
            )}
          </div>
        </div>
      </div>

      {/* Other export options */}
      <div className="relative group">
        <div className="relative flex flex-col items-center justify-between gap-6 overflow-hidden border-t border-t-(--line-2) pt-5 sm:flex-row">
          <div className="relative z-10 space-y-1 text-center sm:text-left">
            <h3 className="text-base font-semibold text-(--t-1)">More export options</h3>
            <p className="text-sm text-(--t-2)">
              Share a link, copy a summary, or download the raw data.
            </p>
          </div>

          <div className="relative z-10 flex flex-wrap justify-center gap-4">
            <button
              onClick={handleCopyShareLink}
              disabled={!activeAuditMeta?.id}
              className={cx(
                "flex items-center gap-3 rounded-xl border border-(--line) bg-(--panel) px-6 py-3 text-xs font-semibold transition-all",
                activeAuditMeta?.id
                  ? "text-(--t-2) hover:border-(--line) hover:bg-(--line-2) hover:text-(--t-1)"
                  : "cursor-not-allowed text-(--t-3)"
              )}
            >
              <Link2 className="h-3.5 w-3.5 text-(--good)" aria-hidden="true" />
              {shareLinkCopied ? "Link copied!" : "Copy share link"}
            </button>
            <button
              onClick={handleCopySummary}
              className="flex items-center gap-3 rounded-xl border border-(--line) bg-(--panel) px-6 py-3 text-xs font-semibold text-(--t-2) transition-all hover:border-(--line) hover:bg-(--line-2) hover:text-(--t-1)"
            >
              <Copy className="h-3.5 w-3.5 text-primary" /> Copy summary
            </button>
            <button
              onClick={handleExportJson}
              className="flex items-center gap-3 rounded-xl border border-(--line) bg-(--panel) px-6 py-3 text-xs font-semibold text-(--t-2) transition-all hover:border-(--line) hover:bg-(--line-2) hover:text-(--t-1)"
            >
              <FileJson className="h-3.5 w-3.5 text-(--purple)" /> Download JSON
            </button>
          </div>
        </div>
        {copyStatus && (
          <div className="absolute -bottom-6 left-1/2 flex -translate-x-1/2 items-center gap-2 font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3) animate-in fade-in slide-in-from-top-2 duration-500">
            <Shield className="h-3 w-3" />
            {copyStatus}
          </div>
        )}
      </div>
    </div>
  );
}
