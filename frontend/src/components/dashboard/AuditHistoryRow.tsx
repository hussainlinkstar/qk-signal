"use client";

import Button from "@/components/ui/Button";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  extractAuditListScores,
  extractAuditUrl,
  formatAuditDate,
  extractAuditStatus,
  scoreBadgeClasses,
  statusBadgeClasses,
} from "@/lib/auditListUtils";
import type { RawAuditHistoryEntry } from "@/types/aiStrategist";
import { normalizeAuditReport } from "@/lib/reportAdapters";
import { generateAuditPdfReport, type ReportSections } from "@/lib/generateAuditPdfReport";
import { DEFAULT_BRANDING } from "@/lib/reportBranding";

export interface AuditHistoryRowProps {
  audit: RawAuditHistoryEntry;
  checked: boolean;
  onToggle: () => void;
}

export const AuditHistoryRow = ({ audit, checked, onToggle }: AuditHistoryRowProps) => {
  const router = useRouter();
  const [isExporting, setIsExporting] = useState(false);

  const scores = extractAuditListScores(audit);
  const url = extractAuditUrl(audit);
  const date = formatAuditDate(audit);
  const status = extractAuditStatus(audit);

  const handleExportPdf = async (e: React.MouseEvent) => {
    e.stopPropagation();

    // Fallback logic from AEO Dashboard for exporting a single report
    let reportData = audit.full_report;
    if (!reportData) {
      alert("This audit has no saved report to export.");
      return;
    }

    // Parse if it's a string
    if (typeof reportData === "string") {
      try {
        reportData = JSON.parse(reportData);
      } catch (err) {
        console.error("Failed to parse full_report JSON string:", err);
        alert("Failed to parse the assessment report data.");
        return;
      }
    }

    setIsExporting(true);
    try {
      const canonicalReport = normalizeAuditReport(reportData);
      if (!canonicalReport) {
        throw new Error("Unable to normalize report data.");
      }

      const reportSections: ReportSections = {
        seo: true,
        geo: true,
        aeo: true,
        technical: true,
        ai: true,
        competitors: false,
      };

      const meta = {
        id: audit.id,
        title: `SEO & AIO Audit: ${String(canonicalReport.site?.url ?? "Unknown Site")}`,
        url: String(audit.url ?? canonicalReport.url ?? ""),
        geoScore: scores.geo,
        seoScore: scores.seo,
        aeoScore: scores.aeo,
        status,
        auditType: typeof audit.audit_type === "string" ? audit.audit_type : "standard",
        createdAt: String(audit.created_at ?? new Date().toISOString()),
      };

      await generateAuditPdfReport(canonicalReport, meta, reportSections, DEFAULT_BRANDING);
    } catch (err) {
      console.error("Failed to export PDF:", err);
      alert("Failed to export PDF: " + (err instanceof Error ? err.message : "Unknown error"));
    } finally {
      setIsExporting(false);
    }
  };

  const handleViewReport = (e: React.MouseEvent) => {
    e.stopPropagation();
    router.push(`/dashboard/audit/${audit.id}`);
  };

  return (
    <tr
      className="border-b border-surface-border/60 transition-colors hover:bg-surface-muted/50 cursor-pointer"
      onClick={onToggle}
    >
      <td className="px-4 py-3">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          onClick={(e) => e.stopPropagation()}
          className="h-4 w-4"
        />
      </td>
      <td className="px-3 py-3">
        <span className="block max-w-[280px] truncate font-medium text-(--t-1)" title={url}>
          {url}
        </span>
      </td>
      <td className="px-3 py-3 text-center">
        <span
          className={`inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ${scoreBadgeClasses(scores.seo)}`}
        >
          {Math.round(scores.seo)}
        </span>
      </td>
      <td className="px-3 py-3 text-center">
        <span
          className={`inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ${scoreBadgeClasses(scores.geo)}`}
        >
          {Math.round(scores.geo)}
        </span>
      </td>
      <td className="px-3 py-3 text-center">
        <span
          className={`inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ${scoreBadgeClasses(scores.aeo)}`}
        >
          {Math.round(scores.aeo)}
        </span>
      </td>
      <td className="px-3 py-3 text-center">
        <span
          className={`inline-flex rounded-full px-2 py-0.5 text-xs font-semibold capitalize ${statusBadgeClasses(status)}`}
        >
          {status}
        </span>
      </td>
      <td className="px-3 py-3 text-right text-xs text-(--t-2)">{date}</td>
      <td className="px-4 py-3 text-right">
        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={handleViewReport}>
            View
          </Button>
          <Button variant="inverse" size="sm" onClick={handleExportPdf} disabled={isExporting}>
            {isExporting ? <Loader2 className="signal-export-spin h-4 w-4" /> : "Export PDF"}
          </Button>
        </div>
      </td>
    </tr>
  );
};
